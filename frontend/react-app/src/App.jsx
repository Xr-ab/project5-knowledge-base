// App.jsx —— 应用最顶层组件：管数据 + 调后端（流式版 + 会话列表 + token 自动续期）
import { useState, useEffect } from 'react'
import './App.css'  // 必须显式 import，Vite 才会把 App.css 打 bundle
import MessageList from './components/MessageList'
import MessageInput from './components/MessageInput'
import ThreadList from './components/ThreadList'

// 相对路径，不写死 IP/端口（开发靠 vite 代理，生产靠同源）
const BACKEND_URL = '/api/v1'

function App() {
  const [messages, setMessages] = useState([])
  const [threadId, setThreadId] = useState('')   // 当前会话 id（空 = 还没建）
  const [threads, setThreads] = useState([])     // 左侧会话列表
  const [aiText, setAiText] = useState('')       // 正在生成的 AI 回复（逐字变长）
  const [aiThinking, setAiThinking] = useState('') // 还没收到字时的提示（思考中/查资料）
  const [isLoading, setIsLoading] = useState(false)  // AI 回话中 = true，禁用发送
  const [token, setToken] = useState('')             // JWT：登录拿到的 access_token
  const [isUploading, setIsUploading] = useState(false) // 上传中文 = true，禁用输入条

  // 登录小助手：专门打 auth/login 拿 token，记进 state 并返回。
  // 首次发消息用它，token 过期（401）也用它重新拿 —— 同一段逻辑复用。
  async function doLogin() {
    const loginRes = await fetch(`${BACKEND_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'xr' }),
    })
    if (!loginRes.ok) throw new Error('登录失败')
    const loginData = await loginRes.json()
    setToken(loginData.access_token)  // 记进 state，下次不用再登
    return loginData.access_token
  }

  // 拉会话列表（侧边栏用）：GET /threads，不需要 token
  async function fetchThreads() {
    try {
      const res = await fetch(`${BACKEND_URL}/threads`)
      if (!res.ok) return
      setThreads(await res.json())
    } catch {
      /* 拉列表失败不阻断聊天，默默忽略 */
    }
  }

  // 组件挂载时拉一次会话列表
  useEffect(() => { fetchThreads() }, [])

  // 切到某个会话：把它的历史消息上屏。
  // ⚠️ 后端存的 role 是 human/ai，前端气泡样式要 user/assistant，这里做映射。
  async function handleSelectThread(id) {
    setThreadId(id)
    setAiText(''); setAiThinking('')
    let tk = token
    if (!tk) tk = await doLogin()        // 读历史要 token，没有先登
    const res = await fetch(`${BACKEND_URL}/chat/${id}`, {
      headers: { Authorization: `Bearer ${tk}` },
    })
    if (!res.ok) return
    const data = await res.json()
    setMessages(
      data.map((m, i) => ({
        id: i,
        role: m.role === 'human' ? 'user' : 'assistant',
        text: m.content,
      }))
    )
  }

  // 新建会话：清空当前会话，下次发消息会建一个新的
  function handleNewThread() {
    setThreadId('')
    setMessages([])
    setAiText(''); setAiThinking('')
  }

  async function handleSend(text) {
    setIsLoading(true)              // 开始回话：锁住按钮
    setAiText('')                   // 清空上一轮的临时气泡
    setAiThinking('AI 正在思考…')    // 立刻显示"思考中"，不等后端响应
    try {
      // 1. 用户消息加进列表
      setMessages((prev) => [...prev, { id: Date.now(), role: 'user', text }])

      // 2. 确保有 token（没有就登录，懒加载）
      let currentToken = token
      if (!currentToken) currentToken = await doLogin()

      // 3. 首次发消息：申请会话 id，并刷新侧边栏
      let tid = threadId
      if (!tid) {
        const res = await fetch(`${BACKEND_URL}/threads`, { method: 'POST' })
        const data = await res.json()
        tid = data.id
        setThreadId(tid)
        fetchThreads()   // 新建后让侧边栏出现这个新会话
      }

      // 4. 发消息（带 token）。封装成函数方便 401 后重试一次
      async function postChat(tk) {
        return fetch(`${BACKEND_URL}/chat/${tid}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${tk}`,
          },
          body: JSON.stringify({ prompt: text }),
        })
      }

      let res = await postChat(currentToken)
      // token 过期（401）→ 自动重新登录拿新 token，重试一次（用户无感）
      if (res.status === 401) {
        currentToken = await doLogin()
        res = await postChat(currentToken)
      }
      if (!res.ok) throw new Error(`聊天接口返回 ${res.status}`)

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
            setAiThinking('AI 正在查资料…')   // 模型决定搜文档：提示换成"查资料"
          } else if (obj.type === 'llm_chunk') {
            if (!started) { started = true; setAiThinking('') }  // 收到首字，关掉"思考中"
            answer += obj.content
            setAiText(answer)                // 通知界面：更新「正在生成」的气泡
          }
        }
      }

      // 6. 流结束：把完整回复正式加入列表，清掉临时状态
      setMessages((prev) => [...prev, { id: Date.now(), role: 'assistant', text: answer }])
      setAiText('')
      setAiThinking('')
    } catch (err) {
      setAiThinking('')
      setMessages((prev) => [...prev, {
        id: Date.now(),
        role: 'assistant',
        text: '⚠️ 连不上后端，确认它在跑着（本机用 8001 起 uvicorn；或 docker compose up）',
      }])
    } finally {
      setIsLoading(false)   // 不管成没成，最后都解锁
    }
  }

  // 上传文档：让知识库 RAG 真正能用（阶段 1 补的）
  async function handleUpload(file) {
    if (!file) return
    setIsUploading(true)
    try {
      // 懒加载 thread：上传也要会话 id，没建过就先建一个
      let tid = threadId
      if (!tid) {
        const res = await fetch(`${BACKEND_URL}/threads`, { method: 'POST' })
        const data = await res.json()
        tid = data.id
        setThreadId(tid)
        fetchThreads()   // 上传也会建会话，顺手刷新侧边栏
      }

      // 用 FormData 装文件。FastAPI 的 UploadFile 参数名是 file，所以 key 必须是 'file'
      const formData = new FormData()
      formData.append('file', file)

      // ⚠️ 发 FormData 时千万别手动设 Content-Type！
      // 浏览器会自动加 'multipart/form-data; boundary=xxx'，boundary 是分隔符。
      // 手动设反而会丢掉 boundary，后端解析不出文件 → 400/422。
      // 后端 upload 接口不要求 Bearer token（只有 chat 要），所以这里不带 Authorization。
      const res = await fetch(`${BACKEND_URL}/documents/upload/${tid}`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) throw new Error(`上传失败 ${res.status}`)

      const data = await res.json()
      setMessages((prev) => [...prev, {
        id: Date.now(),
        role: 'system',
        text: `📄 已上传「${data.file_name}」并入库，可以基于它提问了`,
      }])
    } catch (err) {
      setMessages((prev) => [...prev, {
        id: Date.now(),
        role: 'system',
        text: `⚠️ 上传失败：${err.message}`,
      }])
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="chat-app">
      {/* 左侧会话列表（侧边栏） */}
      <ThreadList threads={threads} activeId={threadId} onSelect={handleSelectThread} onNew={handleNewThread} />
      {/* 右侧聊天区：消息列表 + 输入框 */}
      <div className="chat-main">
        <MessageList messages={messages} aiText={aiText} aiThinking={aiThinking} />
        <MessageInput onSend={handleSend} onUpload={handleUpload} disabled={isLoading || isUploading} />
      </div>
    </div>
  )
}

export default App
