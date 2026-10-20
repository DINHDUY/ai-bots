#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod compose;
mod engine;
mod stack;

use tauri::{Emitter, Manager, State};
use std::sync::Mutex;

pub struct AppState {
    stack: Mutex<stack::Stack>,
}

#[tauri::command]
async fn check_stack_health(state: State<'_, AppState>) -> Result<String, String> {
    let stack = state.stack.lock().unwrap().clone();
    stack.check_health().await
}

#[tauri::command]
async fn get_stack_status(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let stack = state.stack.lock().unwrap();
    Ok(stack.status())
}

#[tauri::command]
async fn stop_stack(state: State<'_, AppState>) -> Result<(), String> {
    let stack = state.stack.lock().unwrap().clone();
    stack.stop().await
}

fn main() {
    let app = tauri::Builder::default()
        .manage(AppState {
            stack: Mutex::new(stack::Stack::new()),
        })
        .invoke_handler(tauri::generate_handler![
            check_stack_health,
            get_stack_status,
            stop_stack,
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();

            // Start the Compose stack on app launch
            tauri::async_runtime::spawn(async move {
                if let Err(e) = stack::Stack::new().start_async().await {
                    let _ = window.emit("stack-error", &e);
                }
            });

            Ok(())
        })
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                tauri::async_runtime::spawn(async move {
                    // Stop Compose stack on close
                    let _ = stack::Stack::new().stop_async().await;
                    std::process::exit(0);
                });
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|_app_handle, event| match event {
        tauri::RunEvent::Ready => {
            println!("App is ready");
        }
        tauri::RunEvent::Exit => {
            println!("App is exiting");
        }
        _ => {}
    });
}
