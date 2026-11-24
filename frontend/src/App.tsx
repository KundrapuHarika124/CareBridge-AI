import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import type { Role } from "./api";
import { useAuth } from "./auth";
import Layout from "./Layout";
import { AdminAppointments, AdminDepartments, AdminDoctors, AdminOverview, AdminSchedules } from "./pages/Admin";
import AppointmentDetail from "./pages/AppointmentDetail";
import Appointments from "./pages/Appointments";
import Assistant from "./pages/Assistant";
import Book from "./pages/Book";
import CareCircle from "./pages/CareCircle";
import CaregiverPatients from "./pages/CaregiverPatients";
import DoctorToday from "./pages/DoctorToday";
import Home from "./pages/Home";
import { Login, Register } from "./pages/Login";
import Notifications from "./pages/Notifications";
import Settings from "./pages/Settings";
import Discover from "./pages/Discover";
import SuperAdmin from "./pages/SuperAdmin";
import { Loading } from "./ui";
import Telemedicine from "./pages/Telemedicine";

export function homePath(role: Role): string {
  if (role === "DOCTOR") return "/doctor";
  if (role === "HOSPITAL_ADMIN") return "/admin";
  if (role === "SUPER_ADMIN") return "/superadmin";
  return "/home";
}

/** Routing guard for convenience only: the backend enforces every permission itself. */
function Guard({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homePath(user.role)} replace />;
  return <Layout>{children}</Layout>;
}

const PEOPLE: Role[] = ["PATIENT", "CAREGIVER"];
const ANYONE: Role[] = ["PATIENT", "CAREGIVER", "DOCTOR", "HOSPITAL_ADMIN", "SUPER_ADMIN"];

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <Loading />
      </div>
    );
  }
  const start = user ? homePath(user.role) : "/login";
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={start} replace /> : <Login />} />
      <Route path="/register" element={user ? <Navigate to={start} replace /> : <Register />} />

      <Route path="/home" element={<Guard roles={PEOPLE}><Home /></Guard>} />
      <Route path="/discover" element={<Guard roles={PEOPLE}><Discover /></Guard>} />
      <Route path="/assistant" element={<Guard roles={PEOPLE}><Assistant /></Guard>} />
      <Route path="/book" element={<Guard roles={PEOPLE}><Book /></Guard>} />
      <Route path="/appointments" element={<Guard roles={PEOPLE}><Appointments /></Guard>} />
      <Route path="/appointments/:id" element={<Guard roles={PEOPLE}><AppointmentDetail /></Guard>} />
      <Route path="/care-circle" element={<Guard roles={["PATIENT"]}><CareCircle /></Guard>} />
      <Route path="/patients" element={<Guard roles={["CAREGIVER"]}><CaregiverPatients /></Guard>} />

      <Route path="/doctor" element={<Guard roles={["DOCTOR"]}><DoctorToday /></Guard>} />
      <Route path="/telemedicine"
        element={
          <Guard roles={["PATIENT", "DOCTOR"]}>
            <Telemedicine />
          </Guard>
        }
      />
      <Route path="/admin" element={<Guard roles={["HOSPITAL_ADMIN"]}><AdminOverview /></Guard>} />
      <Route path="/admin/doctors" element={<Guard roles={["HOSPITAL_ADMIN"]}><AdminDoctors /></Guard>} />
      <Route path="/admin/schedules" element={<Guard roles={["HOSPITAL_ADMIN"]}><AdminSchedules /></Guard>} />
      <Route path="/admin/appointments" element={<Guard roles={["HOSPITAL_ADMIN"]}><AdminAppointments /></Guard>} />
      <Route path="/admin/departments" element={<Guard roles={["HOSPITAL_ADMIN"]}><AdminDepartments /></Guard>} />
      <Route path="/superadmin" element={<Guard roles={["SUPER_ADMIN"]}><SuperAdmin /></Guard>} />

      <Route path="/notifications" element={<Guard roles={ANYONE}><Notifications /></Guard>} />
      <Route path="/settings" element={<Guard roles={ANYONE}><Settings /></Guard>} />
      <Route path="*" element={<Navigate to={start} replace />} />
    </Routes>
  );
}
