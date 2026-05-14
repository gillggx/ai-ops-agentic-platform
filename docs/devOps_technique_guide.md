---
name: project-restrutcture
description: 引導AIOps 平台架構重構:清理退役程式碼、拆分Java 排程服務、導入分散式鎖支援multi-pod, 內網轉移審查。
當使用者輸入 /project-restructure、提到"架構重構"、"services split"、"分散式鎖"、"清除退役程式碼" 時觸發
---

#Project Restructure Skill

指導claude 對AIOps 平台執行架構重構。實作時先讀取當前程式碼確認狀態，不要假設目標清單已過時或已完成

#當前架構

...
aipos-app:8000 (Next.js 前端)
java-backend:8002 (Spring boot, 唯一 DB 主人, JWT auth)
pytho_ai_sidecar:8050 (LangGraph agent, pipeline executor)
ontology_simulator: 8012(資料服務, MongoDB)
...

**已退役**: 'fastapi_backend_service/' (2026-04-25 退役) 。部暑使用systemd, 生產環境不使用Kubernetes。

|目標|核心問題|順序|

|1. 清理退役程式碼|大量已退役 'fastapi_backend_service' 殘留佔用repo、誤導維護者|p1|
|2. 拆分JAVA 排程服務|排程邏輯與api 耦合在同一JVM ，無法獨立擴展/部暑|p2|
|3. 分散式鎖(multi-pod)|同一任務不應該被多個pod重覆執行|p3|
|4. 內網轉移審查|確保所有變更可在離線環境建置與運行|每個目標完成後|


---

## 目標1: 清理退役程程式碼

### 要達成什麼

Repo中不再包含已退役'fastapi_backend_serviecs' 的任何痕跡。所有CI/CD、部署腳本只針對四個活躍服務。

### 關鍵檢查點

-**Grep 整個repo** 對'fastapi_backend_service' 的引用 (排除 '.git/')。
每個引用需判斷: dead reference -> 刪除; 活引用 ->不刪除

-**部署檔案**:'deploy/kubernetes/'、'deploy/helm'、'deploy/fastapi-backend.service' 全部指向已退役服務。
-**CD/CD**: '.gihub/workflows/' 的workflow 指向已退役服務 (實際CI使用Azure devOps 'azure-pipelines-*.yml')。
-**根目錄**: 'main.py'、'Duckerfile'、'pyproject.toml'、'requirements.txt'、'docker-compose.yml' - 讀取內容後確認是否與已退役服務相關
-**需修改而非刪除**: 'start.sh' (含'fastapi_backed_service' 啟動區塊)、'deploy/setup.sh' (引用fastapi_backend_services 的區塊)
-**一次性檔案**: 'tests/', 'scripts/', 'doc/history/', 'docs/mockups/', 'ontology_simulator/verify_*.py', 'resources/' 二進位檔案 - 確認無活用後刪除。

### 驗証

-'grep -r fastapi_backend_service' 整個工作區 = 0 hit ('.git' 除外)
-'start.sh', 'setup.sh' 語法正確 ('bash -n'通過)
-本地啟動不報錯

## 目標2: 拆分Java 排程服務

### 要達成什麼

將'java-backend'中的排程/巡檢/輸詢邏輯抽出為獨立的'java-scheduler' spring boot 服務。兩服務可獨立運行、獨立擴展。

### 拆分原則

-**java-backend (:8002)** - 所有REST controlller, auth, CURD, 業務邏輯。不再有'@Scheduled' 任務
-**java-scheduler** - 所有排程、巡檢執行、事件輪詢、審計保留。有自已Spring Boot main class + '@EnableScheduling'。
-兩服務共享一個PostgreSQL 資料庫
-排程哈呼叫Python sidecar 和Ontology simulator 通過HTTP。
-API service 與排程器的dispatch 通訊通過HTTP POST (不再in-JVM 注入)

### 關鍵耦合點

**實作時先Grep 確認每個耦合點**，因為檔案可能被改名:

- 搜尋 'EventDispatchService' 的注入點 - 這些需改為 HTTP POST 到Scheduler
- 搜尋 'AutoPatrolSchedulerService' 的呼叫點 - 這些需改為HTTP POST 到scheduler 
- 搜尋 '@Scheduled' 註解 - 所有含此註解的類需移到 scheduler
- 設計時需注意 **fail-open**: scheduler 不可用時，dispatch 記錄warn log 但不crash API service

### 驗証

- java-backend 和java-scheduler 可分別獨立啟動
- 建立 alarm 後，scheduler 的dispatch 被觸發
- 巡檢 create/update/delete 後、scheduler 正確註冊/取消排程
- 停止scheduler 後、API service 不crash

--

## 目標3: 分散式鎖 (multi-Pod)

### 要達成什麼

同一任務不被多個pod/節點同時執行。所有服務支援水平擴展

### 核心設計

**scheduler** - Redis 'SET NX' 分散式鎖:
- 搜尋 '@Scheduled' 註解的每個分法，包含分散式鎖
- 搜尋 'AutoPatrolSchedulerService' 中巡檢執行路行，包含分散式鎖
- pod失敗 = 跳過執行 (debug log)，不crash
- Pod TTL = 任務預期持續時間的數倍
- 不使用Redisson (引入過入依賴) ，Spring Data Redis 即可

**API service** - stateless, 不需分散式Pod:
- 確保rediness/liveness probe 可用
- JWT 驗証不依賴本地狀態

**實作時調查其它服務 scale-out前置條件** (不屬於本次重構的程式碼變更，但需記錄為後續工作):
- 前端NextAuth session 是否依賴本地store
- Python sidecar 的agent session 是否存在於記憶体

### 驗証

- 啟動兩個java-scheduler 實例，'@Scheduled' 任務只有一個節點執行
- 巡檢觸發時只有一個節點執行
- 殺死一個節點後，另一個自動接管
- Redis 無殘留Pod key

---

### 目標4: 內網轉移審查

每個目標完成後，執行'/transfer-code-review' 審查變更。特別注意:

- 新增的使賴、端點不引用外部資源
- 新的pom.xml 依賴版本與內網環境相容 (JAVA 17, Spring Boot 3.5.14, Maven)
- 連線配置使用環境變數，不hard code

P1 -> P2 -> P3 -> P4 (每個目標完成後提交一個commit)

### 每步實作前

1. **讀取當前檔案** - Grep/Read 目標檔案，確認那些已經實作，那些尚未開始
2. **識別依賴** - 修改檔案前，檢查誰引用了它，避免引入compile error
3. **小步提交** - 每個邏輯完整的變更批次一個commit

### 遵守的規則

- 新Java 程式碼遵循現有模式: 'JpaRepository' 介面, Flyway migration 順序編號
- 不吞 'save()'例外
- 新增配置使用環境變數 ('${ENV_VAR:default}' 格式)
- 排程服務主類必須有 '@EnableScheduling'
- multi-pod release 使用Lua script 確保原子性

---