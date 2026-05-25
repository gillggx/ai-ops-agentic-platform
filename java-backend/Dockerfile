# Multi-stage Dockerfile for aiops-java-api.
# Stage 1: Maven build (full JDK + maven). Stage 2: thin JRE runtime.
# Final image ~250MB.

FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build

# Copy pom first to leverage Docker layer cache for dependencies.
COPY pom.xml .
RUN mvn -B dependency:go-offline

COPY src ./src
RUN mvn -B clean package -DskipTests

FROM eclipse-temurin:17-jre
WORKDIR /app

# Add a non-root user; Spring Boot doesn't need root.
RUN useradd -r -u 1001 -g root aiops
USER 1001

COPY --from=build /build/target/*.jar /app/app.jar

# Container port — K8s convention. EC2 sets PORT=8002 via env.
EXPOSE 8080
ENV PORT=8080 \
    JAVA_OPTS="-XX:+UseG1GC -Xms256m -Xmx768m" \
    LOG_LEVEL=INFO

ENTRYPOINT ["sh","-c","exec java $JAVA_OPTS -jar /app/app.jar --server.port=${PORT}"]
