package com.aiops.api.sidecar;

import com.aiops.api.config.AiopsProperties;
import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.util.concurrent.TimeUnit;

/**
 * WebClient for calling the Python AI Sidecar (LangGraph Agent, Pipeline Executor, etc.).
 * Injects the service token on every request.
 */
@Configuration
public class PythonSidecarConfig {

	@Bean
	public WebClient pythonSidecarWebClient(AiopsProperties props) {
		var python = props.sidecar().python();

		HttpClient httpClient = HttpClient.create()
				.option(ChannelOption.CONNECT_TIMEOUT_MILLIS, python.connectTimeoutMs())
				.doOnConnected(conn -> conn.addHandlerLast(
						new ReadTimeoutHandler(python.readTimeoutMs(), TimeUnit.MILLISECONDS)));

		return WebClient.builder()
				.baseUrl(python.baseUrl())
				.defaultHeader("X-Service-Token", python.serviceToken())
				.defaultHeader(HttpHeaders.ACCEPT, "application/json")
				.clientConnector(new ReactorClientHttpConnector(httpClient))
				.build();
	}
}
