#include <algorithm>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "wfs_core_engine.h"

namespace py = pybind11;

PYBIND11_MODULE(wfs_core_native, m) {
  m.doc() = "Native Wii U WFS core module";

  py::class_<WfsCoreEngine>(m, "WfsCore")
      .def(py::init<>())
      .def("attach", [](WfsCoreEngine& self, const std::string& device_path, const std::string& otp_path,
                         const std::string& seeprom_path) {
        auto report = self.attach(device_path, otp_path, seeprom_path);
        py::dict out;
        out["attached"] = report.attached;
        out["disk_id"] = report.disk_id;
        out["wfs_verified"] = report.wfs_verified;
        out["key_verified"] = report.key_verified;
        out["fingerprint"] = report.fingerprint;
        return out;
      })
      .def("mkdir", &WfsCoreEngine::mkdir)
      .def("create_file", &WfsCoreEngine::create_file, py::arg("path"), py::arg("size_hint") = 0)
      .def("write_stream", [](WfsCoreEngine& self, const std::string& path, py::bytes data, uint32_t offset) {
        std::string bytes = data;
        std::vector<std::byte> payload(bytes.size());
        std::transform(bytes.begin(), bytes.end(), payload.begin(),
                       [](char c) { return static_cast<std::byte>(static_cast<unsigned char>(c)); });
        return self.write_stream(path, payload, offset);
      })
      .def("delete", &WfsCoreEngine::remove)
      .def("flush", &WfsCoreEngine::flush)
      .def("integrity_check", [](WfsCoreEngine& self, const std::string& scope) {
        auto report = self.integrity_check(scope);
        py::dict out;
        out["ok"] = report.ok;
        out["files"] = report.files;
        out["bytes"] = report.bytes;
        out["scope"] = report.scope;
        out["reason"] = report.reason;
        return out;
      })
      .def("detach", &WfsCoreEngine::detach);
}
