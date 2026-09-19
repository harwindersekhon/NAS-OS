import { Alert, Button, PasswordInput, TextInput } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import { useLogin } from "@/api/auth";

export function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    login.mutate({ username, password });
  };

  return (
    <div className="nasos-login nasos-canvas-texture">
      <div className="nasos-login__panel">
        <div className="nasos-login__brand">
          <span className="nasos-login__dot" aria-hidden="true" />
          <span className="nasos-login__wordmark">NAS-OS</span>
        </div>
        <form onSubmit={handleSubmit} className="nasos-login__form" noValidate>
          <TextInput
            label="Username"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            autoFocus
            autoComplete="username"
            required
          />
          <PasswordInput
            label="Password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            autoComplete="current-password"
            required
          />
          {login.isError && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {login.error instanceof ApiError ? login.error.message : "Sign-in failed"}
            </Alert>
          )}
          <Button type="submit" loading={login.isPending} fullWidth>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
