use std::process::Command;
use std::path::PathBuf;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComposeConfig {
    pub project_name: String,
    pub file: String, // "compose.dev.yml" or "compose.prd.yml"
    pub health_url: String,
    pub wait_seconds: u32,
}

#[derive(Clone)]
pub struct ComposeStack {
    pub config: ComposeConfig,
    pub project_root: PathBuf,
}

impl ComposeStack {
    pub fn new(project_root: PathBuf, config: ComposeConfig) -> Self {
        ComposeStack {
            config,
            project_root,
        }
    }

    pub async fn up(&self) -> Result<(), String> {
        self.ensure_compose_available()?;

        let compose_file = self.project_root.join(&self.config.file);
        if !compose_file.exists() {
            return Err(format!(
                "Compose file not found: {}",
                compose_file.display()
            ));
        }

        println!(
            "Starting Compose stack: {} ({})",
            self.config.project_name, self.config.file
        );

        let output = Command::new("podman")
            .arg("compose")
            .arg("-f")
            .arg(compose_file.to_str().unwrap())
            .arg("-p")
            .arg(&self.config.project_name)
            .arg("up")
            .arg("-d")
            .current_dir(&self.project_root)
            .output()
            .map_err(|e| format!("Failed to run podman compose up: {}", e))?;

        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).to_string());
        }

        println!("Compose stack started");
        Ok(())
    }

    pub async fn down(&self) -> Result<(), String> {
        self.ensure_compose_available()?;

        let compose_file = self.project_root.join(&self.config.file);
        println!("Stopping Compose stack...");

        let output = Command::new("podman")
            .arg("compose")
            .arg("-f")
            .arg(compose_file.to_str().unwrap())
            .arg("-p")
            .arg(&self.config.project_name)
            .arg("down")
            .current_dir(&self.project_root)
            .output()
            .map_err(|e| format!("Failed to run podman compose down: {}", e))?;

        if !output.status.success() {
            eprintln!(
                "Warning: podman compose down had issues: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }

        Ok(())
    }

    pub async fn wait_healthy(&self, timeout_secs: u32) -> Result<(), String> {
        let start = std::time::Instant::now();
        let timeout = std::time::Duration::from_secs(timeout_secs as u64);

        println!("Waiting for services to be ready ({}s timeout)...", timeout_secs);

        loop {
            if start.elapsed() > timeout {
                return Err("Timeout waiting for services to be healthy".to_string());
            }

            match self.check_health().await {
                Ok(true) => {
                    println!("All services are healthy");
                    return Ok(());
                }
                _ => {
                    tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
                }
            }
        }
    }

    pub async fn check_health(&self) -> Result<bool, String> {
        // Try to reach the health URL
        match reqwest::get(&self.config.health_url).await {
            Ok(response) => Ok(response.status().is_success()),
            Err(_) => Ok(false),
        }
    }

    #[allow(dead_code)]
    pub async fn get_logs(&self) -> Result<String, String> {
        let compose_file = self.project_root.join(&self.config.file);

        let output = Command::new("podman")
            .arg("compose")
            .arg("-f")
            .arg(compose_file.to_str().unwrap())
            .arg("-p")
            .arg(&self.config.project_name)
            .arg("logs")
            .current_dir(&self.project_root)
            .output()
            .map_err(|e| format!("Failed to get logs: {}", e))?;

        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    fn ensure_compose_available(&self) -> Result<(), String> {
        let output = Command::new("podman")
            .arg("compose")
            .arg("--version")
            .output()
            .map_err(|e| format!("podman-compose not available: {}", e))?;

        if !output.status.success() {
            return Err("podman-compose is not installed. Install with: pip install podman-compose".to_string());
        }

        Ok(())
    }

    pub fn get_ui_url(&self) -> String {
        // Extract the base URL from the health URL
        // e.g., http://localhost:5174/health -> http://localhost:5174
        self.config.health_url
            .trim_end_matches("/health")
            .to_string()
    }
}
