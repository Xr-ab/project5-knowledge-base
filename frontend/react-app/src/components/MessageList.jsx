// MessageList.jsx —— 消息列表组件（流式版：末尾显示「正在生成」的气泡）
import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'

function MessageList({ messages, aiText, aiThinking }) {
  const endRef = useRef(null)  // 列表最底部的锚点：用来"滚到底"

  // 消息 / 流式文字 / 思考提示 任一变化 → 自动滚到最底（不用手拖滚动条）
  // 依赖数组写这三个，它们任一变就触发滚动
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, aiText, aiThinking])

  return (
    <div className="message-list">
      {/* 已完成的正式消息 */}
      {messages.map((msg) => (
        <div key={msg.id} className={`message message--${msg.role}`}>
          {/* 助手消息可能是 Markdown（代码/列表），用 ReactMarkdown 渲染；用户/系统消息纯文本 */}
          {msg.role === 'assistant' ? (
            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{msg.text}</ReactMarkdown>
          ) : msg.text}
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
          <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{aiText}</ReactMarkdown>
        </div>
      )}

      {/* 锚点：滚到底就滚到这个空 div（useEffect 让它滚到这里） */}
      <div ref={endRef} />
    </div>
  )
}

export default MessageList
