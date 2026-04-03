/**
 * Pretty-prints a JSON value with syntax highlighting using simple spans.
 */
function JsonToken({ value, indent = 0 }) {
  const pad = '  '.repeat(indent)

  if (value === null) return <span className="text-slate-400">null</span>
  if (typeof value === 'boolean') return <span className="text-amber-600">{String(value)}</span>
  if (typeof value === 'number') return <span className="text-blue-600">{value}</span>
  if (typeof value === 'string') return <span className="text-emerald-700">&quot;{value}&quot;</span>

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-500">[]</span>
    return (
      <span>
        {'[\n'}
        {value.map((item, i) => (
          <span key={i}>
            {pad}{'  '}<JsonToken value={item} indent={indent + 1} />
            {i < value.length - 1 ? ',\n' : '\n'}
          </span>
        ))}
        {pad}{']'}
      </span>
    )
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value)
    if (entries.length === 0) return <span className="text-slate-500">{'{}'}</span>
    return (
      <span>
        {'{\n'}
        {entries.map(([k, v], i) => (
          <span key={k}>
            {pad}{'  '}
            <span className="text-indigo-600">&quot;{k}&quot;</span>
            {': '}
            <JsonToken value={v} indent={indent + 1} />
            {i < entries.length - 1 ? ',\n' : '\n'}
          </span>
        ))}
        {pad}{'}'}
      </span>
    )
  }

  return <span>{String(value)}</span>
}

export default function JsonViewer({ data, label }) {
  return (
    <div>
      {label && (
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">{label}</div>
      )}
      <pre className="bg-slate-950 text-slate-200 rounded-xl p-4 text-xs leading-5 overflow-x-auto font-mono whitespace-pre">
        <JsonToken value={data} />
      </pre>
    </div>
  )
}
