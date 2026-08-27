// App.jsx —— 应用最顶层组件：管数据 + 调后端（流式版）
import { useState } from 'react'
import './App.css'  // 必须显式 import，Vite 才会把 App.css 打 bundle
import MessageList from './components/MessageList'
import MessageInput from './components/MessageInput'

// 原来：const BACKEND_URL = 'http://127.0.0.1:8001/api/v1'
// 改成（相对路径，不写死 IP 和端口）：
const BACKEND_URL = '/api/v1'

function App() {
  const [messages, setMessages] = useState([])
  const [threadId, setThreadId] = useState('')
  const [aiText, setAiText] = useState('')       // 正在生成的 AI 回复（逐字变长）
  const [aiThinking, setAiThinking] = useState('') // 还没收到字时的提示（思考中/查资料）
  const [isLoading, setIsLoading] = useState(false)  // AI 回话中 = true，禁用发送

  async function handleSend(text) {
    setIsLoading(true)              // 开始回话：锁住按钮
    setAiText('')                   // 清空上一轮的临时气泡
    setAiThinking('AI 正在思考…')    // 立刻显示"思考中"，不等后端响应
    try {
      // 1. 用户消息加进列表
      setMessages((prev) => [...prev, { id: Date.now(), role: 'user', text }])

      // 2. 首次先登录拿 token（和 threadId 一样的懒加载：没有才调登录接口）
      let currentToken = token
      if (!currentToken) {
        const loginRes = await fetch(`${BACKEND_URL}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: 'xr' }),
        })
        const loginData = await loginRes.json()
        currentToken = loginData.access_token
        setToken(currentToken)
      }

      // 3. 首次发消息：申请会话 id
      let tid = threadId
      if (!tid) {
        const res = await fetch(`${BACKEND_URL}/threads`, { method: 'POST' })
        const data = await res.json()
        tid = data.id
        setThreadId(tid)
      }

      // 4. 发消息（带上 token，后端才放行）
      const res = await fetch(`${BACKEND_URL}/chat/${tid}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${currentToken}`,
        },
        body: JSON.stringify({ prompt: text }),
      })

      // 5. 流式读取：边收边显示（打字机）
      const reader = res.body.getReader()  // 拿水龙头
      const decoder = new TextDecoder()    // 字节→文字翻译官
      let buffer = ''                      // 攒着的半行（网络可能半行到达）
      let answer = ''                      // 局部变量：收集完整回复（避免 state 延迟的坑）
      let started = false                 // 是否已收到第一个字（用来关掉"思考中"）

      while (true) {
        const { done, value } = await reader.read()  // 拧一次水龙头
        if (done) break                              // 流结束

        buffer += decoder.decode(value, { stream: true })  // 字节→文字，追加到攒的尾巴
        const lines = buffer.split('\n')    // 按行切开（后端每行一个 JSON）
        buffer = lines.pop()                // 最后一段可能是不完整的一行，留到下次拼
        for (const line of lines) {
          if (!line.trim()) continue        // 跳过空行
          const obj = JSON.parse(line)
          if (obj.type === 'tool_call') {
            // 模型决定搜文档了：把提示从"思考中"换成"查资料"
            setAiThinking('AI 正在查资料…')
          } else if (obj.type === 'llm_chunk') {
            // 收到第一个字：关掉"思考中"，正式进入打字机
            if (!started) { started = true; setAiThinking('') }
            answer += obj.content                    // 局部变量累加（最终值准）
            setAiText(answer)                        // 通知界面：更新「正在生成」的气泡
          }
        }
      }

      // 6. 流结束：把完整回复正式加入列表，清掉临时状态
      setMessages((prev) => [...prev, { id: Date.now(), role: 'assistant', text: answer }])
      setAiText('')
      setAiThinking('')
    } catch (err) {
      // 抓不到后端 / 网络断了：别让用户干等"思考中"，给一句明白话
      setAiThinking('')
      setMessages((prev) => [...prev, {
        id: Date.now(),
        role: 'assistant',
        text: '⚠️ 连不上后端，确认它在 8000 端口跑着（uvicorn app.main:app --reload）',
      }])
    } finally {
      setIsLoading(false)   // 不管成没成，最后都解锁
    }
  }

  return (
    <div className="chat-app">
      <MessageList messages={messages} aiText={aiText} aiThinking={aiThinking} />
      <MessageInput onSend={handleSend} disabled={isLoading} />
    </div>
  )
}

export default App
