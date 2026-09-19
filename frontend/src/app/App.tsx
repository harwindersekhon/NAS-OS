import { useEffect } from "react";

import { useSession } from "@/api/auth";
import { wsHub } from "@/api/ws";
import { Desktop } from "@/shell/Desktop";
import { Login } from "@/shell/Login";
import { Taskbar } from "@/shell/Taskbar";

export function App() {
  const { data: session, isLoading } = useSession();
  const authenticated = Boolean(session);

  useEffect(() => {
    if (!authenticated) return undefined;
    wsHub.start();
    return () => wsHub.stop();
  }, [authenticated]);

  if (isLoading) {
    return <div className="nasos-boot" />;
  }

  if (!authenticated) {
    return <Login />;
  }

  return (
    <div className="nasos-shell">
      <Taskbar />
      <Desktop />
    </div>
  );
}
