/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 画布 / 背景层级：接近黑色的深灰，非纯黑
        canvas: '#0c0e11',
        base: '#0f1216',
        // 卡片层级
        surface: {
          1: '#16191f',
          2: '#1b1f27',
          3: '#22272f',
          4: '#2a303a',
        },
        // 主强调色：薄荷 / 青绿。300 向后微调亮度以满足深色背景上的文本对比度。
        mint: {
          50: '#e6fff6',
          100: '#c3fbe8',
          200: '#8ff3d3',
          300: '#7eecc8',
          400: '#2dd4a8',
          500: '#19b98f',
          600: '#0f9575',
          700: '#0c745d',
        },
        // 辅助色。整体亮度上调，保证在深色画布上的可读性。
        knowledge: '#8fbaff', // 蓝：知识
        collab: '#bfa9ff', // 紫：协作
        remind: '#ffb87a', // 橙：提醒
        rose: '#ff97a8',
      },
      borderRadius: {
        // 三级语义圆角：小组件 8px / 卡片容器 12px / 浮层与抽屉 16px
        control: '8px',
        soft: '12px',
        card: '14px',
        overlay: '16px',
        pill: '999px',
      },
      fontSize: {
        base: ['14px', '22px'],
      },
      boxShadow: {
        card: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)',
        pop: '0 24px 60px -20px rgba(0,0,0,0.75)',
        panel: '-24px 0 48px -24px rgba(0,0,0,0.7)',
        input: 'inset 0 0 0 1px rgba(255,255,255,0.08)',
      },
      fontFamily: {
        sans: [
          '"PingFang SC"',
          '"Microsoft YaHei"',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'slide-in': {
          '0%': { transform: 'translateX(24px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        'grow-x': {
          '0%': { transform: 'scaleX(0)' },
          '100%': { transform: 'scaleX(1)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.28s ease-out',
        'scale-in': 'scale-in 0.2s ease-out',
        'slide-in': 'slide-in 0.28s cubic-bezier(0.22, 1, 0.36, 1)',
        'grow-x': 'grow-x 0.7s cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
}
