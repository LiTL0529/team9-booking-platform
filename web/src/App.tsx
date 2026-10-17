import { createContext, useContext, useEffect, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { api, Claims, currentClaims, signOut } from './api';
import Browse from './pages/Browse';
import MyBookings from './pages/MyBookings';
import Inbox from './pages/Inbox';
import MerchantConsole from './pages/MerchantConsole';
import Admin from './pages/Admin';
import Login from './pages/Login';

interface Session {
  user: Claims | null;
  setUser: (user: Claims | null) => void;
}

const SessionContext = createContext<Session>({ user: null, setUser: () => {} });
export const useSession = () => useContext(SessionContext);

const isMerchant = (u: Claims | null) => !!u?.groups.some((g) => g === 'merchant_admin' || g === 'merchant_staff');
const isAdmin = (u: Claims | null) => !!u?.groups.includes('platform_admin');
const isCustomer = (u: Claims | null) => !!u?.groups.includes('customer');

function UnreadBadge() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => api.unreadCount().then((r) => alive && setCount(r.unread)).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  return count > 0 ? <span className="badge">{count}</span> : null;
}

export default function App() {
  const [user, setUser] = useState<Claims | null>(currentClaims());
  const navigate = useNavigate();

  const logout = () => {
    signOut();
    setUser(null);
    navigate('/');
  };

  return (
    <SessionContext.Provider value={{ user, setUser }}>
      <header className="topbar">
        <div className="brand">
          <span className="logo">◎</span> CourtHub
          <small>multi-merchant booking</small>
        </div>
        <nav>
          <NavLink to="/" end>Find a slot</NavLink>
          {isCustomer(user) && <NavLink to="/bookings">My bookings</NavLink>}
          {user && <NavLink to="/inbox">Inbox <UnreadBadge /></NavLink>}
          {isMerchant(user) && <NavLink to="/merchant">Merchant console</NavLink>}
          {isAdmin(user) && <NavLink to="/admin">Platform admin</NavLink>}
        </nav>
        <div className="who">
          {user ? (
            <>
              <span title={user.groups.join(', ')}>{user.username}</span>
              <button className="link" onClick={logout}>Sign out</button>
            </>
          ) : (
            <NavLink to="/login" className="button small">Sign in</NavLink>
          )}
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Browse />} />
          <Route path="/login" element={<Login />} />
          <Route path="/bookings" element={user ? <MyBookings /> : <Navigate to="/login" />} />
          <Route path="/inbox" element={user ? <Inbox /> : <Navigate to="/login" />} />
          <Route path="/merchant" element={isMerchant(user) ? <MerchantConsole /> : <Navigate to="/login" />} />
          <Route path="/admin" element={isAdmin(user) ? <Admin /> : <Navigate to="/login" />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </SessionContext.Provider>
  );
}
