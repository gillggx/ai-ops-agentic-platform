# Multi-stage Dockerfile for aiops-java-scheduler.
# Same JDK / Spring Boot stack as java-api; different main class.

FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build

COPY pom.xml .
RUN mvn -B dependency:go-offline

COPY src ./src
RUN mvn -B clean package -DskipTests

FROM eclipse-temurin:17-jre
WORKDIR /app

RUN useradd -r -u 1001 -g root aiops
USER 1001

COPY --from=build /build/target/*.jar /app/app.jar

EXPOSE 8080
ENV PORT=8080 \
    JAVA_OPTS="-XX:+UseG1GC -Xms256m -Xmx512m" \
    LOG_LEVEL=INFO

ENTRYPOINT ["sh","-c","exec java $JAVA_OPTS -jar /app/app.jar --server.port=${PORT}"]
