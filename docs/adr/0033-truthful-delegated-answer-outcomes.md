# ADR 0033：代答资料不足与模型不可用不计回答

状态：接受（现有 PersonalAgent 与市场状态投影；持久 DelegatedQuery 另行实施）。

没有匹配依据的请求返回 insufficient_evidence，无引用、confidence none。真实合成返回“信息不足”也使用同一状态。模型未配置、调用失败或空结果返回 blocked，无引用、confidence none，并使用静态不可用说明。删除旧的“已归纳”模板；命中数量不能替代一次真实回答。真正生成的回答继续使用 answered，敏感确认与拒绝维持原规则。

直接采用命令要求 answered、非空答复和引用；blocked/insufficient_evidence 不能生成采纳记忆或贡献记录。此要求不证明旧市场 post 的答复来源。旧市场采用入口返回 409 verified_delegated_query_required，零新增 Source/Memory/Relation/Point；前端不再提供该动作。状态帖不能被伪造成高置信答案。持久 query/Artifact 采用验证另行实施。

市场匹配审计记录实际状态，公开 post 使用对应的静态交付/待确认/不可用/资料不足/拒绝说明。Timeline 与动态 API 保留新增状态，无法识别的旧状态回到 open，不猜成 answered。标题使用中性“回应/处理”，只在实际 answered 的动态句子中说已解答。前端用中文区分状态，失败或资料不足的记录不能显示完成代答。

测试的成功分支显式注入回答模型 adapter，不再凭无模型模板证明成功。空资料、模型自身报告不足、失败与未配置有独立回归；市场 API/前端验证不可用状态不会变成已回答。它不代表代答语义质量、当前双方/来源的原子授权、重启恢复或已证明的结果采用。持久 DelegatedQuery、受限答复 Artifact、bilateral consent 版本与项目范围、重新授权与来源验证继续开发。
