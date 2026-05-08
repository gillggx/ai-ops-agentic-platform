plugins {
	java
	id("org.springframework.boot") version "3.5.0"
	id("io.spring.dependency-management") version "1.1.7"
}

group = "com.aiops"
version = "0.0.1-SNAPSHOT"

java {
	toolchain {
		languageVersion = JavaLanguageVersion.of(21)
	}
}

repositories {
	mavenCentral()
}

dependencies {
	// Pull in java-backend as a library — gives access to entities, repos,
	// AiopsProperties, SimulatorClient, ObjectMapper config, etc. without
	// duplicating code. Component scanning in AiopsSchedulerApplication is
	// kept narrow so we don't accidentally instantiate API-side beans
	// (security filters, REST controllers, etc.).
	implementation(project(":java-backend"))

	// Spring Boot starters (re-declare; gradle doesn't transit api()).
	implementation("org.springframework.boot:spring-boot-starter-actuator")
	implementation("org.springframework.boot:spring-boot-starter-data-jpa")
	implementation("org.springframework.boot:spring-boot-starter-web")
	implementation("org.springframework.boot:spring-boot-starter-webflux")
	implementation("org.springframework.boot:spring-boot-starter-validation")

	// JPA extras matching java-backend (so entity classes load identically).
	implementation("org.hibernate.orm:hibernate-envers")
	implementation("com.vladmihalcea:hibernate-types-60:2.21.1")
	implementation("com.pgvector:pgvector:0.1.4")

	compileOnly("org.projectlombok:lombok")
	runtimeOnly("org.postgresql:postgresql")
	annotationProcessor("org.projectlombok:lombok")

	testImplementation("org.springframework.boot:spring-boot-starter-test")
	testCompileOnly("org.projectlombok:lombok")
	testAnnotationProcessor("org.projectlombok:lombok")
	testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.withType<Test> {
	useJUnitPlatform()
}

tasks.named<org.springframework.boot.gradle.tasks.bundling.BootJar>("bootJar") {
	archiveFileName.set("aiops-scheduler.jar")
}

springBoot {
	mainClass.set("com.aiops.scheduler.AiopsSchedulerApplication")
}
