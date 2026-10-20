use std::process::Command;

#[derive(Debug, Clone)]
pub struct ContainerEngine {
    pub runtime: String,
    #[allow(dead_code)]
    pub socket_path: Option<String>,
    pub is_running: bool,
}

impl ContainerEngine {
    pub fn detect() -> Result<Self, String> {
        // Check if podman is available
        match Self::check_podman() {
            Ok(mut engine) => {
                engine.check_running()?;
                Ok(engine)
            }
            Err(e) => Err(format!(
                "Podman not found or not running: {}. Please install Podman first.",
                e
            )),
        }
    }

    fn check_podman() -> Result<Self, String> {
        let output = Command::new("podman")
            .arg("--version")
            .output()
            .map_err(|e| format!("Failed to run podman: {}", e))?;

        if !output.status.success() {
            return Err("Podman is not installed or not accessible".to_string());
        }

        let socket_path = Self::get_socket_path();
        Ok(ContainerEngine {
            runtime: "podman".to_string(),
            socket_path,
            is_running: false,
        })
    }

    fn get_socket_path() -> Option<String> {
        // Linux rootless
        if let Ok(runtime_dir) = std::env::var("XDG_RUNTIME_DIR") {
            return Some(format!("{}/podman/podman.sock", runtime_dir));
        }

        // macOS Podman Machine
        #[cfg(target_os = "macos")]
        {
            if let Ok(output) = Command::new("podman")
                .arg("machine")
                .arg("inspect")
                .arg("--format")
                .arg("{{.ConnectionInfo.PodmanSocket.Path}}")
                .output()
            {
                if output.status.success() {
                    let path = String::from_utf8_lossy(&output.stdout)
                        .trim()
                        .to_string();
                    if !path.is_empty() {
                        return Some(path);
                    }
                }
            }
        }

        // Linux rootful or default
        Some("/run/podman/podman.sock".to_string())
    }

    fn check_running(&mut self) -> Result<(), String> {
        let output = Command::new("podman")
            .arg("info")
            .output()
            .map_err(|e| format!("Failed to check Podman status: {}", e))?;

        self.is_running = output.status.success();
        if !self.is_running {
            Err("Podman is not running".to_string())
        } else {
            Ok(())
        }
    }

    pub fn ensure_machine_running() -> Result<(), String> {
        #[cfg(target_os = "macos")]
        {
            // Check if machine is running
            let output = Command::new("podman")
                .arg("machine")
                .arg("list")
                .arg("--format")
                .arg("table {{.Name}}\t{{.Running}}")
                .output()
                .map_err(|e| format!("Failed to list machines: {}", e))?;

            let stdout = String::from_utf8_lossy(&output.stdout);
            if !stdout.contains("true") {
                // Start the default machine
                println!("Starting Podman Machine...");
                let status = Command::new("podman")
                    .arg("machine")
                    .arg("start")
                    .status()
                    .map_err(|e| format!("Failed to start Podman Machine: {}", e))?;

                if !status.success() {
                    return Err("Failed to start Podman Machine".to_string());
                }
                std::thread::sleep(std::time::Duration::from_secs(5));
            }
        }

        Ok(())
    }

    #[allow(dead_code)]
    pub fn run_command(&self, args: &[&str]) -> Result<String, String> {
        let output = Command::new(&self.runtime)
            .args(args)
            .output()
            .map_err(|e| format!("Failed to run {}: {}", self.runtime, e))?;

        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).to_string());
        }

        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}
