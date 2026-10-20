use crate::compose::{ComposeConfig, ComposeStack};
use crate::engine::ContainerEngine;
use serde_json::json;
use std::path::PathBuf;

#[derive(Clone)]
pub struct Stack {
    engine: Option<ContainerEngine>,
    compose: Option<ComposeStack>,
}

impl Stack {
    pub fn new() -> Self {
        let engine = ContainerEngine::detect().ok();

        let compose = engine.as_ref().map(|_| {
            let project_root = Self::get_project_root();
            let config = ComposeConfig {
                project_name: "agentbot-dev".to_string(),
                file: "compose.dev.yml".to_string(),
                health_url: "http://localhost:8001/health".to_string(),
                wait_seconds: 120,
            };
            ComposeStack::new(project_root, config)
        });

        Stack { engine, compose }
    }

    pub async fn start_async(&self) -> Result<(), String> {
        ContainerEngine::ensure_machine_running()?;

        if let Some(compose) = &self.compose {
            compose.up().await?;
            compose.wait_healthy(compose.config.wait_seconds).await?;
            Ok(())
        } else {
            Err("Container engine not available".to_string())
        }
    }

    pub async fn stop_async(&self) -> Result<(), String> {
        if let Some(compose) = &self.compose {
            compose.down().await?;
            Ok(())
        } else {
            Err("Container engine not available".to_string())
        }
    }

    pub async fn check_health(&self) -> Result<String, String> {
        match self.engine.as_ref() {
            None => Err("Podman not available - please install Podman first".to_string()),
            Some(_) => {
                if let Some(compose) = &self.compose {
                    match compose.check_health().await {
                        Ok(true) => Ok("Ready! Opening application...".to_string()),
                        Ok(false) => Err("Services starting...".to_string()),
                        Err(e) => Err(format!("Health check failed: {}", e)),
                    }
                } else {
                    Err("Compose not configured".to_string())
                }
            }
        }
    }

    pub fn status(&self) -> serde_json::Value {
        json!({
            "engine": self.engine.as_ref().map(|e| &e.runtime),
            "running": self.engine.as_ref().map(|e| e.is_running),
            "compose_file": self.compose.as_ref().map(|c| &c.config.file),
            "ui_url": self.compose.as_ref().map(|c| c.get_ui_url()),
        })
    }

    pub async fn stop(&self) -> Result<(), String> {
        self.stop_async().await
    }

    fn get_project_root() -> PathBuf {
        // Get the parent directory of the desktop app
        // The app is bundled relative to the project root
        std::env::current_exe()
            .ok()
            .and_then(|exe_path| exe_path.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| PathBuf::from("."))
    }
}

impl Default for Stack {
    fn default() -> Self {
        Self::new()
    }
}
