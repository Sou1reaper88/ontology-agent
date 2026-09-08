import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/auth": "http://127.0.0.1:8001",
            "/execute": "http://127.0.0.1:8001",
            "/users": "http://127.0.0.1:8001",
            "/roles": "http://127.0.0.1:8001",
            "/permissions": "http://127.0.0.1:8001",
            "/conversations": "http://127.0.0.1:8001",
            "/prompts": "http://127.0.0.1:8001",
            "/sql": "http://127.0.0.1:8001",
            "/ontology/": "http://127.0.0.1:8001",
            "/ontology-packages": "http://127.0.0.1:8001",
            "/evaluations": "http://127.0.0.1:8001",
            "/audit-logs": "http://127.0.0.1:8001",
        },
    },
});
