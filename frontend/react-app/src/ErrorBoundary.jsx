import React from 'react'

// ErrorBoundary —— 渲染兜底：任何组件渲染时抛异常，React 会把整棵树卸掉变成白屏。
// 有这层兜底，崩溃会显示错误信息 + 一键刷新，而不是一片空白（白屏最难受的是不知道发生了什么）。
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  // 子组件渲染抛错时触发：把错误存进 state，走下面的兜底 UI
  static getDerivedStateFromError(error) {
    return { error }
  }

  // 顺带打进控制台，方便排查（保留完整堆栈）
  componentDidCatch(error, info) {
    console.error('渲染崩溃：', error, info?.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: '100vh', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 14,
          fontFamily: 'system-ui, "Microsoft YaHei", sans-serif', padding: 24, textAlign: 'center',
        }}>
          <h2 style={{ margin: 0 }}>😢 页面渲染出错了</h2>
          <pre style={{
            maxWidth: 720, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            background: '#f6f8fa', border: '1px solid #d0d7de', borderRadius: 10,
            padding: '12px 16px', fontSize: 12.5, color: '#57606a', margin: 0,
          }}>{String(this.state.error?.message || this.state.error)}</pre>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            style={{ padding: '9px 22px', borderRadius: 9, border: 'none', cursor: 'pointer',
              background: '#2563eb', color: '#fff', fontSize: 14 }}
          >刷新页面</button>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
