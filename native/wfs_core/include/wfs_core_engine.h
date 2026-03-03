#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

class WfsDevice;

struct AttachReport {
  bool attached;
  std::string disk_id;
  bool wfs_verified;
  bool key_verified;
  std::string fingerprint;
};

struct IntegrityReport {
  bool ok;
  uint64_t files;
  uint64_t bytes;
  std::string scope;
  std::string reason;
};

class WfsCoreEngine {
 public:
  WfsCoreEngine();

  AttachReport attach(const std::string& device_path, const std::string& otp_path, const std::string& seeprom_path);
  void mkdir(const std::string& path);
  void create_file(const std::string& path, uint32_t size_hint);
  size_t write_stream(const std::string& path, const std::vector<std::byte>& data, uint32_t offset);
  void remove(const std::string& path);
  void flush();
  IntegrityReport integrity_check(const std::string& scope);
  void detach();

 private:
  std::shared_ptr<WfsDevice> ensure_attached() const;
  std::string device_path_;
  std::string fingerprint_;
  std::shared_ptr<WfsDevice> wfs_device_;
};

