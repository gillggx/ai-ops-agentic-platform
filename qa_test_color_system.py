import os
import re

def verify_color_system():
    print("⏳ [QA 啟動] 驗證前端色板設定 (Design System Check)...")
    
    # 假設使用 Tailwind CSS，檢查 config 檔 (若使用純 CSS，可改為檢查 index.css)
    # 請依據實際前端專案結構調整路徑 (例如: frontend/tailwind.config.js)
    config_path = "tailwind.config.js" 
    
    # 若專案結構是在 frontend 資料夾下，自動嘗試切換
    if not os.path.exists(config_path) and os.path.exists(f"frontend/{config_path}"):
        config_path = f"frontend/{config_path}"
        
    if not os.path.exists(config_path):
        print(f"⚠️ [警告] 找不到 {config_path}，請小柯確認前端設定檔路徑。若使用 CSS Variables，請修改 QA 腳本掃描目標。")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read().upper()

    # 必須包含的 Hex 色碼清單 (PRD 定義)
    required_colors = {
        "Primary (深藍)": "#0A6EF0",
        "Accent (霓虹青)": "#2AA3AB",
        "Background (極淺灰)": "#F8FAFC",
        "Success (科技綠)": "#2AA238"
    }

    missing_colors = []
    for name, hex_code in required_colors.items():
        if hex_code not in content:
            missing_colors.append(f"{name}: {hex_code}")

    if missing_colors:
        print("❌ [QA 阻擋] 設定檔中遺漏了以下核心色碼：")
        for color in missing_colors:
            print(f"  - {color}")
        print("💡 要求 Claude 重新檢查 tailwind.config.js 的 extend colors 設定。")
    else:
        print("🎉 [QA 通過] 所有核心色碼皆已精準寫入設定檔！底層 UI 規範確立。")

if __name__ == "__main__":
    verify_color_system()