interface Props {
  type: string;
}

export function UnsupportedPlaceholder({ type }: Props) {
  return (
    <div style={{
      background: "#1a202c",
      border: "1px dashed #4a5568",
      borderRadius: 8,
      padding: "24px",
      color: "#718096",
      fontSize: 13,
      textAlign: "center",
    }}>
      Unsupported visualization type: <code style={{ color: "#f6ad55" }}>{type}</code>
    </div>
  );
}
