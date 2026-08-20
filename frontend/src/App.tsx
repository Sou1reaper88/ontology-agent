import { Navigate, Route, Routes } from "react-router-dom";
import MainLayout from "./components/Layout";
import Login from "./pages/Login";
import Result from "./pages/Result";
import Chat from "./pages/Chat";
import DataQuery from "./pages/DataQuery";
import Ontology from "./pages/Ontology";
import Admin from "./pages/Admin";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<Chat />} />
        <Route path="ontology" element={<Ontology />} />
        <Route path="query" element={<DataQuery />} />
        <Route path="result/:queryId" element={<Result />} />
        <Route path="admin" element={<Admin />} />
      </Route>
    </Routes>
  );
}

export default App;
