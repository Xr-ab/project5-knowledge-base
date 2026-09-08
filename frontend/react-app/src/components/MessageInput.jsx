// MessageInput.jsx —— 输入框组件（递话员：把文字交给 App；现在也管上传文档）
import { useState, useRef } from 'react'

function MessageInput({ onSend, onUpload, disabled }) {
  // 自己的小账本：inputText = 输入框里当前的文字
  const [inputText, setInputText] = useState('')
  // 隐藏 file input 的「遥控器」：用 ref 间接点它（真正的 <input type=file> 太丑，藏起来）
  const fileInputRef = useRef(null)

  // 点「发送」或按回车时触发（表单提交）
  function handleSubmit(e) {
    e.preventDefault()            // 阻止表单默认「刷新页面」的行为
    if (inputText.trim() === '') return  // 空消息不发（trim 去掉首尾空格）
    onSend(inputText)             // 把文字「递」给 App 的 handleSend
    setInputText('')              // 发完清空输入框
  }

  // 点「上传文档」按钮 → 间接触发隐藏的 file input（打开系统的文件选择框）
  function handleFileClick() {
    fileInputRef.current?.click()
  }

  // 用户在文件框选了文件 → 拿到文件对象，交给 App 的 handleUpload
  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''  // 清空：下次选同一个文件也能再次触发 onChange
  }

  return (
    // form：把输入框 + 按钮包在一起，回车也能提交
    <form className="message-input" onSubmit={handleSubmit}>
      {/* 隐藏的文件选择框：display:none 藏起来，靠上面的按钮间接点它 */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".pdf,.docx,.txt"   // 给个提示（后端也校验，不匹配会 400）
        style={{ display: 'none' }}
      />
      {/* 上传按钮：type=button 防止触发表单提交（否则会连带发消息） */}
      <button type="button" className="upload-btn" onClick={handleFileClick} disabled={disabled}>
        📎 上传文档
      </button>
      {/* 受控输入框：value 听 state 的，onChange 更新 state；处理中禁用 */}
      <input
        type="text"
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        placeholder="输入消息..."
        disabled={disabled}
      />
      {/* 发送按钮：处理中禁用，显示「转圈 + 处理中...」比纯文字更直观 */}
      <button type="submit" disabled={disabled} className="send-btn">
        {disabled ? (
          <>
            <span className="spinner" />
            处理中...
          </>
        ) : (
          '发送'
        )}
      </button>
    </form>
  )
}

export default MessageInput
