import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api, type AuthStatus } from "./api";
import { Logo, PlusIcon } from "./components/icons";
import { useQueue } from "./hooks";
import Login from "./pages/Login";
import Library from "./pages/Library";
import RecipeView from "./pages/RecipeView";
import RecipeEdit from "./pages/RecipeEdit";
import Import from "./pages/Import";
import Tags from "./pages/Tags";
import Settings from "./pages/Settings";

export default function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);

  const check = useCallback(async () => {
    try {
      setAuth(await api.get<AuthStatus>("/auth/status"));
    } catch {
      setAuth({ authenticated: false, setup_required: false, password_from_env: false });
    }
  }, []);

  useEffect(() => {
    check();
    const onUnauth = () => check();
    window.addEventListener("collander:unauthorized", onUnauth);
    return () => window.removeEventListener("collander:unauthorized", onUnauth);
  }, [check]);

  if (!auth) return null;
  if (!auth.authenticated) return <Login setup={auth.setup_required} onDone={check} />;
  return <Shell auth={auth} />;
}

function Shell({ auth }: { auth: AuthStatus }) {
  const { items } = useQueue();
  const pending = items.filter((i) => i.status === "queued" || i.status === "processing").length;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label="Collander home">
            <Logo />
            <span>Collander</span>
          </Link>
          {pending > 0 && (
            <Link to="/import" className="queue-pill" title={`${pending} import(s) in progress`}>
              <span className="dot" aria-hidden="true" />
              <span className="hide-sm">Importing</span> {pending}
            </Link>
          )}
          <nav>
            <NavLink to="/" end className="navlink">
              Recipes
            </NavLink>
            <NavLink to="/import" className="navlink">
              Import
            </NavLink>
            <NavLink to="/tags" className="navlink secondary">
              Tags
            </NavLink>
            <NavLink to="/settings" className="navlink">
              Settings
            </NavLink>
          </nav>
          <Link to="/new" className="btn primary" aria-label="Add a recipe">
            <PlusIcon />
            <span className="hide-sm">Add</span>
          </Link>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/r/:id" element={<RecipeView />} />
          <Route path="/r/:id/edit" element={<RecipeEdit />} />
          <Route path="/new" element={<RecipeEdit />} />
          <Route path="/import" element={<Import queueItems={items} />} />
          <Route path="/tags" element={<Tags />} />
          <Route path="/settings" element={<Settings auth={auth} />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Back to recipes</Link></p>} />
        </Routes>
      </main>
    </div>
  );
}
