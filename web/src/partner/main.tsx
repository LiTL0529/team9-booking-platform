import React from 'react';
import ReactDOM from 'react-dom/client';
import FitPal from './FitPal';
import { loadConfig } from './partnerApi';
import './fitpal.css';

loadConfig().then(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <FitPal />
    </React.StrictMode>,
  );
});
