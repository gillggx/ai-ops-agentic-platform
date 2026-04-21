package com.aiops.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableAsync
public class AiopsApiApplication {

	public static void main(String[] args) {
		SpringApplication.run(AiopsApiApplication.class, args);
	}
}
