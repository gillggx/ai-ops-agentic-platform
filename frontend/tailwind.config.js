/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
        },
        // Phase 13 Design System (PRD: prd_phase_13_color_system.md)
        primary:    '#0A6EF0',  // 主色 — Header, 主要按鈕, 重要標題
        accent:     '#2AA3AB',  // 輔助色 — Hover, Active Tab, Toggle
        background: '#F8FAFC',  // 整體背景 (Slate 50)
        surface:    '#FFFFFF',  // 卡片與表單背景
        success:    '#2AA238',  // 狀態：正常 (科技綠)
        textprimary: '#1E293B', // 文字主色
      },
      animation: {
        'spin-slow': 'spin 1.5s linear infinite',
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-in': 'slideIn 0.25s ease-out',
      },
      keyframes: {
        fadeIn: { from: { opacity: 0 }, to: { opacity: 1 } },
        slideIn: { from: { transform: 'translateX(100%)' }, to: { transform: 'translateX(0)' } },
      },
    },
  },
  plugins: [],
}
