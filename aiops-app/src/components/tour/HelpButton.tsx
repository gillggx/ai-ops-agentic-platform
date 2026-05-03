"use client";

/** Floating ? button — bottom-left of viewport. Always visible; click to
 *  re-launch the active surface's tour. */

interface Props {
  onClick: () => void;
  title?: string;
}

export default function HelpButton({ onClick, title = "重看導覽" }: Props) {
  return (
    <button className="tour-help" onClick={onClick} title={title}>
      ?
    </button>
  );
}
