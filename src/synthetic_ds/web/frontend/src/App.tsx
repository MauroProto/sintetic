import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "@/pages/DashboardPage";
import { DatasetDashboardPage } from "@/pages/DatasetDashboardPage";
import { NewRunPage } from "@/pages/NewRunPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="dataset" element={<DatasetDashboardPage />} />
        <Route path="new" element={<NewRunPage />} />
        <Route path="runs/:jobId" element={<RunDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="open/:jobId" element={<RedirectToRun />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

function RedirectToRun() {
  const path = window.location.pathname.replace("/open/", "/runs/");
  return <Navigate to={path} replace />;
}
