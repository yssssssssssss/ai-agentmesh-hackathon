"""SQL candidate constraints; content checks still run on bounded search hits."""
from __future__ import annotations

from dataclasses import dataclass

from agentmesh.models import MemoryLayer


@dataclass(frozen=True)
class MemorySearchFilter:
    actor_id: str
    workspace_id: str
    project_id: str | None
    layers: frozenset[MemoryLayer]
    memory_types: frozenset[str] | None = None

    def sql(self, alias: str) -> tuple[str, list[str]]:
        if alias not in {'records_fts', 'rf'}:
            raise ValueError('unsupported_search_alias')
        conditions = [
            "json_extract(cm.payload, '$.workspace_id') = ?",
            "(json_extract(cm.payload, '$.project_id') IS NULL OR json_extract(cm.payload, '$.project_id') = ?)",
            "json_extract(cm.payload, '$.facts') IS NULL",
            "json_extract(cm.payload, '$.procedure') IS NULL",
            "json_extract(cm.payload, '$.evidence_withdrawn_at') IS NULL",
            """(
              (cm.collection = 'user_memory_items' AND json_extract(cm.payload, '$.scope') = 'private'
               AND COALESCE(json_extract(cm.payload, '$.status'), 'active') = 'active')
              OR (cm.collection = 'memory_items' AND (
                (json_extract(cm.payload, '$.status') = 'accepted'
                 AND json_extract(cm.payload, '$.scope') IN ('project', 'team_accepted'))
                OR (json_extract(cm.payload, '$.provenance') IS NULL
                    AND json_extract(cm.payload, '$.scope') = 'project'
                    AND COALESCE(json_extract(cm.payload, '$.status'), 'proposed')
                        NOT IN ('disputed', 'deprecated', 'expired', 'archived'))
              ))
            )""",
        ]
        parameters = [self.workspace_id, self.project_id or '']
        layer_values = sorted(self.layers)
        conditions.append(
            "COALESCE(json_extract(cm.payload, '$.layer'), CASE WHEN "
            "json_extract(cm.payload, '$.scope') = 'project' THEN 'mid_term' ELSE 'long_term' END) "
            f"IN ({','.join('?' for _ in layer_values) or 'NULL'})"
        )
        parameters.extend(layer_values)
        if self.memory_types is not None:
            types = sorted(self.memory_types)
            conditions.append(f"COALESCE(json_extract(cm.payload, '$.memory_type'), 'note') "
                              f"IN ({','.join('?' for _ in types) or 'NULL'})")
            parameters.extend(types)
        conditions.append("""
          (
            (cm.collection = 'user_memory_items' AND json_extract(cm.payload, '$.user_id') = ?)
            OR (cm.collection = 'memory_items' AND (
              json_extract(cm.payload, '$.scope') NOT IN ('team_accepted', 'team_candidate')
              OR json_extract(cm.payload, '$.team_id') IS NULL
              OR EXISTS (SELECT 1 FROM records actor WHERE actor.collection = 'users' AND actor.id = ?
                         AND json_extract(actor.payload, '$.role') IN ('admin', 'team_lead'))
              OR EXISTS (SELECT 1 FROM records membership WHERE membership.collection = 'team_memberships'
                         AND json_extract(membership.payload, '$.user_id') = ?
                         AND json_extract(membership.payload, '$.team_id') = json_extract(cm.payload, '$.team_id'))
            ))
          )
        """)
        parameters.extend([self.actor_id] * 3)
        non_memory = '0' if self.memory_types is not None else (
            f"{alias}.collection NOT IN ('memory_items', 'user_memory_items')"
        )
        authority = """
          EXISTS (SELECT 1 FROM records current_actor
                  WHERE current_actor.collection = 'users' AND current_actor.id = ?
                    AND COALESCE(json_extract(current_actor.payload, '$.status'), 'active') = 'active'
                    AND json_extract(current_actor.payload, '$.workspace_id') = ?)
        """
        authority_parameters = [self.actor_id, self.workspace_id]
        if self.project_id is not None:
            authority += """
              AND EXISTS (SELECT 1 FROM records current_project
                WHERE current_project.collection = 'projects' AND current_project.id = ?
                  AND json_extract(current_project.payload, '$.workspace_id') = ?
                  AND (COALESCE(json_array_length(current_project.payload, '$.member_ids'), 0) = 0
                       OR EXISTS (SELECT 1 FROM json_each(current_project.payload, '$.member_ids') WHERE value = ?)))
            """
            authority_parameters.extend([self.project_id, self.workspace_id, self.actor_id])
        clause = f"""
          AND {authority}
          AND ({non_memory} OR EXISTS (
            SELECT 1 FROM records cm WHERE cm.collection = {alias}.collection AND cm.id = {alias}.record_id
              AND cm.collection IN ('memory_items', 'user_memory_items')
              AND {' AND '.join(conditions)}
          ))
        """
        return clause, [*authority_parameters, *parameters]
