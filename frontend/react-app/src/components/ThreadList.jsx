// ThreadList.jsx —— 左侧会话列表（侧边栏）：点哪个就切到哪个会话
function ThreadList({ threads, activeId, onSelect, onNew }) {
  return (
    <aside className="sidebar">
      {/* 新建会话按钮：清空当前，下次发消息建新的 */}
      <button className="new-thread-btn" onClick={onNew}>＋ 新建会话</button>

      <div className="thread-list">
        {/* 没会话时给个占位提示 */}
        {threads.length === 0 && <div className="thread-empty">还没有会话</div>}

        {/* 把后端给的每个会话渲染成一条可点按钮 */}
        {threads.map((t) => (
          <button
            key={t.id}
            // 当前选中的会话高亮（active 样式）
            className={`thread-item ${t.id === activeId ? 'active' : ''}`}
            onClick={() => onSelect(t.id)}
          >
            {/* title 是后端给的标题；没标题就用 id 前 8 位顶着 */}
            {t.title || String(t.id).slice(0, 8)}
          </button>
        ))}
      </div>
    </aside>
  )
}

export default ThreadList
