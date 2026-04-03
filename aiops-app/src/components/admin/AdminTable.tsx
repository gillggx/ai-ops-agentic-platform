"use client";

interface Column<T> {
  key: keyof T | string;
  label: string;
  render?: (row: T) => React.ReactNode;
}

interface AdminTableProps<T extends { id: string }> {
  columns: Column<T>[];
  rows: T[];
  onEdit?: (row: T) => void;
  onDelete?: (id: string) => void;
}

export function AdminTable<T extends { id: string }>({
  columns, rows, onEdit, onDelete,
}: AdminTableProps<T>) {
  return (
    <div style={{ overflowX: "auto", background: "#1a202c", borderRadius: 8, border: "1px solid #2d3748" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ background: "#141b2d", borderBottom: "1px solid #2d3748" }}>
            {columns.map((col) => (
              <th key={String(col.key)} style={{ padding: "10px 16px", textAlign: "left", color: "#a0aec0", fontWeight: 600 }}>
                {col.label}
              </th>
            ))}
            {(onEdit || onDelete) && (
              <th style={{ padding: "10px 16px", textAlign: "right", color: "#a0aec0" }}>操作</th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length + 1} style={{ padding: "24px", textAlign: "center", color: "#718096" }}>
                尚無資料
              </td>
            </tr>
          ) : rows.map((row) => (
            <tr key={row.id} style={{ borderBottom: "1px solid #2d3748", background: "#1a202c" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#243044")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "#1a202c")}
            >
              {columns.map((col) => (
                <td key={String(col.key)} style={{ padding: "10px 16px", color: "#e2e8f0" }}>
                  {col.render
                    ? col.render(row)
                    : String((row as Record<string, unknown>)[String(col.key)] ?? "")}
                </td>
              ))}
              {(onEdit || onDelete) && (
                <td style={{ padding: "10px 16px", textAlign: "right" }}>
                  {onEdit && (
                    <button onClick={() => onEdit(row)} style={btnStyle("#2b6cb0")}>編輯</button>
                  )}
                  {onDelete && (
                    <button onClick={() => onDelete(row.id)} style={{ ...btnStyle("#c53030"), marginLeft: 8 }}>刪除</button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function btnStyle(bg: string): React.CSSProperties {
  return {
    background: bg, color: "#fff", border: "none", borderRadius: 4,
    padding: "4px 12px", cursor: "pointer", fontSize: 12,
  };
}
