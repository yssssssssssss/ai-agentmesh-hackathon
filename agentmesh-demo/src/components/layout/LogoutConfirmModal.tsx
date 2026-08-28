import { useNavigate } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { useSession } from '../../store/SessionContext'

interface LogoutConfirmModalProps {
  open: boolean
  onClose: () => void
}

/**
 * 退出登录确认弹窗。
 * 与真实业务保持一致的口径:退出只清空前端登录态,你的知识资产、工作理解、
 * 授权记录都保留在服务端,重新用 ERP 登录后仍可继续使用。
 */
export function LogoutConfirmModal({ open, onClose }: LogoutConfirmModalProps) {
  const navigate = useNavigate()
  const { logout } = useSession()

  const handleConfirm = async () => {
    await logout()
    navigate('/login', { replace: true })
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="退出我的数字人?"
      subtitle="退出后需要重新使用 ERP 统一登录才能进入。"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="danger"
            icon={<LogOut className="h-4 w-4" />}
            onClick={handleConfirm}
          >
            确认退出
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-[13.5px] leading-relaxed text-slate-300">
        <p>
          你的知识资产、工作理解与授权记录都保存在服务端,不会因为退出而丢失 ——
          重新登录后可以继续使用。
        </p>
        <p className="text-slate-400">
          若你只是切换视角查看不同权限页面,可以在账号菜单里直接使用「Demo 身份预览」,无需退出登录。
        </p>
      </div>
    </Modal>
  )
}
