// MessageInput.jsx —— 输入框组件（递话员：把文字交给 App）
import { useState } from 'react'

function MessageInput({ onSend, disabled }) {
  // 自己的小账本：inputText = 输入框里当前的文字
  const [inputText, setInputText] = useState('')

  // 点「发送」或按回车时触发（表单提交）
  function handleSubmit(e) {
    e.preventDefault()            // 阻止表单默认「刷新页面」的行为
    if (inputText.trim() === '') return  // 空消息不发（trim 去掉首尾空格）
    onSend(inputText)             // 把文字「递」给 App 的 handleSend
    setInputText('')              // 发完清空输入框
  }

  return (
    // form：把输入框 + 按钮包在一起，回车也能提交
    <form className="message-input" onSubmit={handleSubmit}>
      {/* 受控输入框：value 听 state 的，onChange 更新 state；回复中禁用 */}
      <input
        type="text"
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        placeholder="输入消息..."
        disabled={disabled}
      />
      {/* 发送按钮：回复中禁用，显示「回复中...」 */}
      <button type="submit" disabled={disabled}>
        {disabled ? '回复中...' : '发送'}
      </button>
    </form>
  )
}

export default MessageInput
