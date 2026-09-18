// ThreadList.jsx —— 左侧会话列表（侧边栏）：点哪个就切到哪个会话
function ThreadList({ threads, activeId, onSelect, onNew, onDelete }) {
  return (
    <aside className="sidebar">
      {/* 新建会话按钮：清空当前，下次发消息建新的 */}
      <button className="new-thread-btn" onClick={onNew}>＋ 新建会话</button>

      <div className="thread-list">
        {/* 没会话时给个占位提示 */}
        {threads.length === 0 && <div className="thread-empty">还没有会话</div>}

        {/* 把后端给的每个会话渲染成一条：主按钮切换 + 小按钮删除 */}
        {threads.map((t) => (
          <div
            key={t.id}
            // 当前选中的会话高亮（active 样式）
            className={`thread-item ${t.id === activeId ? 'active' : ''}`}
          >
            <button
              className="thread-item-main"
              // title 是后端给的标题；没标题就用 id 前 8 位顶着
              onClick={() => onSelect(t.id)}
              title={t.title || String(t.id).slice(0, 8)}
            >
              {t.title || String(t.id).slice(0, 8)}
            </button>
            <button
              className="thread-delete"
              // 删除按钮不触发切换：stopPropagation 掐断冒泡（原来整个条目是一个大按钮）
              onClick={(e) => { e.stopPropagation(); onDelete(t.id) }}
              title="删除会话"
            >×</button>
          </div>
        ))}
      </div>
    </aside>
  )
}

export default ThreadList
