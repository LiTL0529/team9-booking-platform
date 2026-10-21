import { createContext, useContext, useEffect, useState } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api, Claims, currentClaims, signOut } from './api';
import Browse from './pages/Browse';
import MyBookings from './pages/MyBookings';
import Inbox from './pages/Inbox';
import MerchantConsole from './pages/MerchantConsole';
import Admin from './pages/Admin';
import Login from './pages/Login';
import { Icon, ToastProvider } from './ui';

interface Session {
  user: Claims | null;
  setUser: (user: Claims | null) => void;
}

const SessionContext = createContext<Session>({ user: null, setUser: () => {} });
export const useSession = () => useContext(SessionContext);

export const isMerchant = (u: Claims | null) => !!u?.groups.some((g) => g === 'merchant_admin' || g === 'merchant_staff');
export const isAdmin = (u: Claims | null) => !!u?.groups.includes('platform_admin');
export const isCustomer = (u: Claims | null) => !!u?.groups.includes('customer');

/** Pages fire this after reading or creating notifications so the header badge updates at once. */
export const NOTIFICATIONS_CHANGED = 'courthub:notifications-changed';

function roleLabel(u: Claims): string {
  if (isAdmin(u)) return 'Platform admin';
  if (u.groups.includes('merchant_admin')) return 'Merchant admin';
  if (u.groups.includes('merchant_staff')) return 'Merchant staff';
  return 'Customer';
}

function UnreadBadge() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => api.unreadCount().then((r) => alive && setCount(r.unread)).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    window.addEventListener(NOTIFICATIONS_CHANGED, load);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener(NOTIFICATIONS_CHANGED, load);
    };
  }, []);
  return count > 0 ? <span className="badge" aria-label={`${count} unread`}>{count}</span> : null;
}

export default function App() {
  const [user, setUser] = useState<Claims | null>(currentClaims());
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => setMenuOpen(false), [location.pathname]);

  const logout = () => {
    signOut();
    setUser(null);
    navigate('/');
  };

  return (
    <SessionContext.Provider value={{ user, setUser }}>
      <ToastProvider>
        <header className={`topbar${menuOpen ? ' open' : ''}`}>
          <div className="topbar-inner">
            <Link to="/" className="brand" aria-label="CourtHub home">
              <span className="brand-mark"><Icon name="court" size={20} /></span>
              <span>
                <span className="brand-name">CourtHub</span>
                <span className="brand-sub">One booking app for every venue</span>
              </span>
            </Link>
            <button className="btn-ghost icon-btn menu-toggle" onClick={() => setMenuOpen((o) => !o)}
              aria-expanded={menuOpen} aria-label="Menu"><Icon name={menuOpen ? 'x' : 'menu'} size={22} /></button>
            <nav className="nav" aria-label="Main">
              <NavLink to="/" end><Icon name="search" size={17} />Find a slot</NavLink>
              {isCustomer(user) && <NavLink to="/bookings"><Icon name="ticket" size={17} />My bookings</NavLink>}
              {user && <NavLink to="/inbox"><Icon name="bell" size={17} />Inbox <UnreadBadge /></NavLink>}
              {isMerchant(user) && <NavLink to="/merchant"><Icon name="building" size={17} />Merchant console</NavLink>}
              {isAdmin(user) && <NavLink to="/admin"><Icon name="shield" size={17} />Platform admin</NavLink>}
            </nav>
            <div className="account">
              {user ? (
                <>
                  <div className="user-chip" title={user.groups.join(', ')}>
                    <span className="avatar">{user.username.slice(0, 2)}</span>
                    <span><strong>{user.username}</strong><small>{roleLabel(user)}</small></span>
                  </div>
                  <button className="btn-ghost icon-btn" onClick={logout} title="Sign out" aria-label="Sign out">
                    <Icon name="logout" />
                  </button>
                </>
              ) : (
                <NavLink to="/login" state={{ from: location.pathname }} className="button btn-sm">
                  <Icon name="user" size={16} />Sign in
                </NavLink>
              )}
            </div>
          </div>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<Browse />} />
            <Route path="/login" element={<Login />} />
            <Route path="/bookings" element={user ? <MyBookings /> : <Navigate to="/login" state={{ from: '/bookings' }} />} />
            <Route path="/inbox" element={user ? <Inbox /> : <Navigate to="/login" state={{ from: '/inbox' }} />} />
            <Route path="/merchant" element={isMerchant(user) ? <MerchantConsole /> : <Navigate to="/login" state={{ from: '/merchant' }} />} />
            <Route path="/admin" element={isAdmin(user) ? <Admin /> : <Navigate to="/login" state={{ from: '/admin' }} />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
        <footer className="footer">
          <div>
            <span>CourtHub · Team 9 multi-merchant booking platform</span>
            <span className="spacer" />
            <span>Times shown in Singapore time (UTC+8)</span>
          </div>
        </footer>
      </ToastProvider>
    </SessionContext.Provider>
  );
}
