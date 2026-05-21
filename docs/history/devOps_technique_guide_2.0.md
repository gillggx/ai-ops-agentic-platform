---
name: prepare-for-deployment
description: 部署到K8S/隔離環境前，檢查並修復程式碼不一致問題，為每個服務建立 run.sh 重啟包裝指令
---

# Prepare for Deployment Skill

## 總覽

兩項任務:
1.**修復程式碼不一致** - 版本、port、服務名稱必須在所有檔案中一致
2.**建立 run.sh** - 每個服務各一個簡單的K8S 重啟包裝

## 目標版本

Python 3.11、Node.js 20.18、Java 17、Spring Boot 3.5.14、Maven。

## K8s 架構注意事項

每個application 各自建立獨立的Docker image，expose port 8080，container 會將8080 對應到port 80。
服務之間用HTTP 呼叫，不用mage 內部port。DB 在獨立container 中，不在同一個image 內

## 任務 1: 修復不一致

請收集deploy scripts, system units、READMEs、nginx.conf、pom.xml、source code的資訊，然後修復任何不匹配。

重點檢查
- JDK 版本必須是 Temurin 17 (任何 script 都不能用21)
- python 版本必須是3.11
- nginx.conf 必須proxy 到正確的port
- README 必須符合當前架構
- java-backend README : ./gradlew -> mvn spring-boot:run
- start.sh: 如果引用退役服務，標記為deprecated
- deploy scripts 必須與 pom.xml 版本一致

## 任務 2: 為每個服務建立 run.sh

在 deploy/<service>-run.sh 建立 run.sh，簡單重啟包裝即可。**不處理依賴檢查或優雅關閉** (由K8s startup probe / preStop hook 負責) 。

**All services use the same pattern:**

'''shell
#!/bin/sh
ETL_HOME=/userapp/
CONFIG_HOME=/userapp/config
CMD="<start command for this service>"
echo $CMD
while true;
do
    $CMD
    returnCode=$?
    echo "returnCode:" $returnCode
done
'''

**Service CMD details**

|Service|CMD|
|java-backend|java-Dlogging.config=$(CONFIG_HOME).logback.xml -jar /userapp/aiops-api.jar --spring.profiles.active=prod --spring.config.location=${CONFIG_HOME}|
|java-scheduler | Same pattern, different JAR name|
|python_ai_sidecar | Same pattern as sidecar|
|aiops-app | node server.js (or based on Dockerfile)|

組態從env vars 或/userapp/config/ 讀取，不能寫死

