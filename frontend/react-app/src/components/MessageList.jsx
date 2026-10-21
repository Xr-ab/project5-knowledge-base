// MessageList.jsx —— 消息列表组件（流式版：末尾显示「正在生成」的气泡）
import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'

// SourceList —— 引用来源卡片：把「这句话凭什么这么说」摆到台面上
// 数据来自后端 artifact（不是正文），所以正文干净、引用独立
//
// ⚠️ 分数有两种量纲，展示方式必须分开（详见后端 reranker.py 注释）：
//   cosine：0~1 的相似度，越大越像 —— 可以直接显示数值，<0.45 打淡色提示
//   rerank：cross-encoder 的 logits，可负、无上界 —— 显示 "-0.481" 对用户毫无意义，
//           而且原来的 0.45 阈值拿到这里完全不成立，改成高/中/低标签
//
// 分档不是拍脑袋：实测 26 题里「含答案的片段」精排分中位数 3.83、p10 2.67，
// 「不含答案的片段」中位数 1.74。所以 3 分往上才是"明确命中"，1 分往下是"基本无关"。
// 注意低档不是 <0：后端 rerank_min_score=0 已经把负分片段丢掉了，
// 若这里还写 <0，这个档位永远显示不出来。
const RERANK_BANDS = [
  { min: 3, label: '高' },
  { min: 1, label: '中' },
  { min: -Infinity, label: '低' },
]

function rerankLabel(score) {
  return RERANK_BANDS.find((b) => score >= b.min).label
}

function SourceList({ sources }) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="sources">
      <div className="sources-title">引用来源 · {sources.length} 个片段</div>
      {sources.map((s) => {
        const isRerank = s.score_type === 'rerank'
        const label = isRerank ? rerankLabel(s.score) : null
        const weak = isRerank ? s.score < 1 : s.score < 0.45
        return (
          <div className="source-item" key={s.index ?? s.file_name + s.score}>
            <div className="source-head">
              <span className="source-index">[{s.index}]</span>
              <span className="source-name" title={s.document_id || s.file_name}>{s.file_name}</span>
              <span
                className={`source-score${weak ? ' source-score--weak' : ''}`}
                title={isRerank ? `精排分数 ${s.score}（logits，非相似度）` : `余弦相似度 ${s.score}`}
              >
                {isRerank ? `相关度${label}` : typeof s.score === 'number' ? s.score.toFixed(3) : s.score}
              </span>
            </div>
            <p className="source-snippet">{s.snippet}</p>
          </div>
        )
      })}
    </div>
  )
}

function MessageList({ messages, aiText, aiThinking }) {
  const endRef = useRef(null)  // 列表最底部的锚点：用来"滚到底"

  // 消息 / 流式文字 / 思考提示 任一变化 → 自动滚到最底（不用手拖滚动条）
  // 依赖数组写这三个，它们任一变就触发滚动
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, aiText, aiThinking])

  return (
    <div className="message-list">
      {/* 一条都没有（且没有正在生成的临时气泡）→ 空状态欢迎语，主区不至于一片白 */}
      {messages.length === 0 && !aiText && !aiThinking && (
        <div className="empty-state">
          <h2>项目5 · AI 知识库</h2>
          <p>上传文档进知识库，再向它提问。</p>
          <p className="empty-state-hint">试试："根据知识库总结部署方案"，或点左侧「＋ 新建会话」开新话题。</p>
        </div>
      )}

      {/* 已完成的正式消息 */}
      {messages.map((msg) => (
        <div
          key={msg.id}
          // 带引用的回答多一个修饰类：引用区需要更方的边角（圆气泡里塞卡片太挤）
          className={`message message--${msg.role}${msg.sources?.length ? ' message--cited' : ''}`}
        >
          {/* 助手消息可能是 Markdown（代码/列表），用 ReactMarkdown 渲染；用户/系统消息纯文本 */}
          {msg.role === 'assistant' ? (
            <>
              <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{msg.text}</ReactMarkdown>
              <SourceList sources={msg.sources} />
            </>
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
