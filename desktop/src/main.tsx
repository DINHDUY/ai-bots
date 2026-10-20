import React, { useState, useEffect } from "react";
import ReactDOM from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";

function App() {
  const [status, setStatus] = useState<string>("Initializing...");
  const [error, setError] = useState<string>("");
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    let attempts = 0;
    const maxAttempts = 60;
    const checkInterval = setInterval(async () => {
      attempts++;
      try {
        const healthStatus: string = await invoke("check_stack_health");
        setStatus(healthStatus);

        if (healthStatus.includes("Ready")) {
          setIsReady(true);
          clearInterval(checkInterval);
        }
      } catch (err) {
        const errorMsg = typeof err === "string" ? err : String(err);
        setStatus(`Starting services... (${attempts}/${maxAttempts})`);
        setError("");

        if (attempts >= maxAttempts) {
          setError(
            `Services did not start within ${maxAttempts * 2} seconds. ${errorMsg}`
          );
          clearInterval(checkInterval);
        }
      }
    }, 2000);

    return () => clearInterval(checkInterval);
  }, []);

  if (error) {
    return (
      <div style={styles.container}>
        <div style={styles.error}>
          <h1>Error</h1>
          <p>{error}</p>
          <button
            onClick={() => window.location.reload()}
            style={styles.button}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!isReady) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>
          <div style={styles.spinner}></div>
          <h2>Agent Control Desktop</h2>
          <p>{status}</p>
        </div>
      </div>
    );
  }

  // Once services are ready, the window background should load the app
  // via window.location or a webview (handled by Tauri window config)
  return (
    <div style={styles.container}>
      <p style={{ textAlign: "center", marginTop: "50px" }}>
        Loading application...
      </p>
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    width: "100vw",
    height: "100vh",
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    color: "#fff",
  },
  loading: {
    textAlign: "center" as const,
  },
  spinner: {
    width: "40px",
    height: "40px",
    border: "4px solid rgba(255,255,255,0.3)",
    borderTop: "4px solid white",
    borderRadius: "50%",
    animation: "spin 1s linear infinite",
    margin: "0 auto 20px",
  },
  error: {
    background: "rgba(0,0,0,0.2)",
    padding: "30px",
    borderRadius: "8px",
    maxWidth: "400px",
    textAlign: "center" as const,
  },
  button: {
    padding: "10px 20px",
    background: "#667eea",
    color: "white",
    border: "none",
    borderRadius: "4px",
    cursor: "pointer",
    fontSize: "16px",
    marginTop: "20px",
  },
};

// Add keyframe animation
const style = document.createElement("style");
style.textContent = `
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
`;
document.head.appendChild(style);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
