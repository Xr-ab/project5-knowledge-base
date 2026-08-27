// MessageList.jsx —— 消息列表组件（流式版：末尾显示「正在生成」的气泡）
function MessageList({ messages, aiText, aiThinking }) {
  return (
    <div className="message-list">
      {/* 已完成的正式消息 */}
      {messages.map((msg) => (
        <div key={msg.id} className={`message message--${msg.role}`}>
          {msg.text}
        </div>
      ))}

      {/* 还没收到字：显示"思考中/查资料"提示气泡（带三点跳动动画） */}
      {aiThinking && (
        <div className="message message--assistant message--thinking">
          {aiThinking}<span className="dots"><i>.</i><i>.</i><i>.</i></span>
        </div>
      )}

      {/* 正在生成的 AI 回复：aiText 非空时，额外画一个助手气泡，逐字更新 */}
      {aiText && (
        <div className="message message--assistant">
          {aiText}
        </div>
      )}
    </div>
  )
}

export default MessageList
