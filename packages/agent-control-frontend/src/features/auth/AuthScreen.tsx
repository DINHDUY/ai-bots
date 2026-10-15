import { useState } from "react";
import type { FormEvent } from "react";

import { api, type User } from "../../api/client";
import styles from "./auth.module.css";

type Props = { onSignedIn: (user: User) => void };

export function AuthScreen({ onSignedIn }: Props) {
  return (
    <main className={styles.page}>
      <div className={styles.forms}>
        <AuthForm
          title="Sign in"
          path="/api/login"
          passwordAutocomplete="current-password"
          submitLabel="Sign in"
          onSignedIn={onSignedIn}
        />
        <AuthForm
          title="Create account"
          path="/api/register"
          passwordAutocomplete="new-password"
          submitLabel="Register"
          onSignedIn={onSignedIn}
        />
      </div>
    </main>
  );
}

function AuthForm({
  title,
  path,
  passwordAutocomplete,
  submitLabel,
  onSignedIn,
}: {
  title: string;
  path: string;
  passwordAutocomplete: string;
  submitLabel: string;
  onSignedIn: (user: User) => void;
}) {
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const user = await api<User>(path, {
        method: "POST",
        body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
      });
      onSignedIn(user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed");
    }
  }

  return (
    <form className={styles.card} onSubmit={onSubmit}>
      <h1>{title}</h1>
      <label>
        Username
        <input name="username" autoComplete="username" required />
      </label>
      <label>
        Password
        <input name="password" type="password" autoComplete={passwordAutocomplete} required />
      </label>
      <button className="primary" type="submit">{submitLabel}</button>
      <p className="error">{error}</p>
    </form>
  );
}
