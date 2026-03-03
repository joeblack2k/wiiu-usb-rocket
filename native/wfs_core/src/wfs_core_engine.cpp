#include "wfs_core_engine.h"

#include <algorithm>
#include <filesystem>
#include <iomanip>
#include <ios>
#include <sstream>
#include <stdexcept>
#include <string_view>

#include <wfslib/wfslib.h>

namespace {

constexpr uint64_t kFnv1aOffsetBasis = 14695981039346656037ULL;
constexpr uint64_t kFnv1aPrime = 1099511628211ULL;

std::string make_fingerprint(std::string_view input) {
  uint64_t hash = kFnv1aOffsetBasis;
  for (unsigned char value : input) {
    hash ^= static_cast<uint64_t>(value);
    hash *= kFnv1aPrime;
  }

  std::ostringstream stream;
  stream << std::hex << std::setw(16) << std::setfill('0') << hash;
  return stream.str();
}

std::string normalize_path(const std::string& path) {
  std::filesystem::path fs_path(path);
  auto normalized = fs_path.lexically_normal().generic_string();
  if (normalized.empty()) {
    return "/";
  }
  if (normalized.front() != '/') {
    return "/" + normalized;
  }
  return normalized;
}

void validate_absolute_path(const std::string& path, bool allow_root = true) {
  if (path.empty() || path.front() != '/') {
    throw std::runtime_error("WFS path must be absolute");
  }

  for (const auto& part : std::filesystem::path(path)) {
    auto token = part.string();
    if (token == "." || token == "..") {
      throw std::runtime_error("WFS path traversal tokens are not allowed");
    }
  }

  if (!allow_root && normalize_path(path) == "/") {
    throw std::runtime_error("Root path is not allowed for this operation");
  }
}

std::string validate_and_normalize_path(const std::string& path, bool allow_root = true) {
  validate_absolute_path(path, allow_root);
  return normalize_path(path);
}

std::string validate_title_id(const std::string& title_id) {
  if (title_id.empty()) {
    throw std::runtime_error("title_id must be non-empty");
  }
  if (title_id.find('/') != std::string::npos || title_id.find('\\') != std::string::npos) {
    throw std::runtime_error("title_id must not contain path separators");
  }
  if (title_id == "." || title_id == ".." || title_id.find("..") != std::string::npos) {
    throw std::runtime_error("title_id must not contain traversal tokens");
  }
  return title_id;
}

std::vector<std::string> split_parts(const std::string& path) {
  std::filesystem::path fs_path(path);
  std::vector<std::string> parts;
  for (const auto& part : fs_path) {
    auto token = part.string();
    if (token.empty() || token == "/") {
      continue;
    }
    parts.push_back(token);
  }
  return parts;
}

std::pair<std::string, std::string> parent_and_leaf(const std::string& path) {
  std::filesystem::path fs_path(path);
  auto parent = fs_path.parent_path().string();
  auto leaf = fs_path.filename().string();
  if (parent.empty()) {
    parent = "/";
  }
  return {parent, leaf};
}

std::shared_ptr<Directory> resolve_directory(const std::shared_ptr<WfsDevice>& device,
                                             const std::string& path,
                                             bool create_missing) {
  auto current = device->GetRootDirectory();
  if (!current.has_value()) {
    throw WfsException(current.error());
  }

  for (const auto& part : split_parts(path)) {
    auto next = (*current)->GetDirectory(part);
    if (next.has_value()) {
      current = std::move(next);
      continue;
    }
    if (create_missing && next.error() == WfsError::kEntryNotFound) {
      auto created = (*current)->CreateDirectory(part);
      if (!created.has_value()) {
        throw WfsException(created.error());
      }
      current = std::move(created);
      continue;
    }
    throw WfsException(next.error());
  }

  return *current;
}

void scan_directory(const std::shared_ptr<Directory>& directory, uint64_t& files, uint64_t& bytes) {
  for (auto it = directory->begin(); it != directory->end(); ++it) {
    auto entry = *it;
    if (!entry.entry.has_value()) {
      throw WfsException(entry.entry.error());
    }
    const auto& node = *entry.entry;
    if (node->is_file()) {
      auto file = std::dynamic_pointer_cast<File>(node);
      if (file) {
        ++files;
        bytes += file->Size();
      }
      continue;
    }
    if (node->is_directory()) {
      auto child = std::dynamic_pointer_cast<Directory>(node);
      if (child) {
        scan_directory(child, files, bytes);
      }
    }
  }
}

void delete_entry_recursive(const std::shared_ptr<Directory>& directory, const std::string& name) {
  auto entry = directory->GetEntry(name);
  if (!entry.has_value()) {
    throw WfsException(entry.error());
  }

  const auto& node = *entry;
  if (node->is_directory()) {
    auto child = std::dynamic_pointer_cast<Directory>(node);
    if (!child) {
      throw std::runtime_error("invalid directory entry");
    }

    std::vector<std::string> child_names;
    for (auto it = child->begin(); it != child->end(); ++it) {
      auto child_entry = *it;
      if (!child_entry.entry.has_value()) {
        throw WfsException(child_entry.entry.error());
      }
      child_names.push_back(child_entry.name);
    }

    for (const auto& child_name : child_names) {
      delete_entry_recursive(child, child_name);
    }
  }

  auto deleted = directory->DeleteEntry(name);
  if (!deleted.has_value()) {
    throw WfsException(deleted.error());
  }
}

}  // namespace

WfsCoreEngine::WfsCoreEngine() = default;

AttachReport WfsCoreEngine::attach(const std::string& device_path,
                                   const std::string& otp_path,
                                   const std::string& seeprom_path) {
  auto otp = std::unique_ptr<OTP>(OTP::LoadFromFile(otp_path));
  auto seeprom = std::unique_ptr<SEEPROM>(SEEPROM::LoadFromFile(seeprom_path));
  auto usb_key = seeprom->GetUSBKey(*otp);

  auto device = std::make_shared<FileDevice>(std::filesystem::path(device_path), 9, 0, false, false);
  bool key_verified = Recovery::CheckWfsKey(device, usb_key);
  auto wfs_device = Recovery::OpenWfsDeviceWithoutDeviceParams(device, usb_key);
  if (!wfs_device.has_value()) {
    throw WfsException(wfs_device.error());
  }

  device_path_ = device_path;
  fingerprint_ = make_fingerprint(device_path + std::string(reinterpret_cast<const char*>(usb_key.data()), usb_key.size()));
  wfs_device_ = *wfs_device;

  return {
      .attached = true,
      .disk_id = device_path,
      .wfs_verified = true,
      .key_verified = key_verified,
      .fingerprint = fingerprint_,
  };
}

std::shared_ptr<WfsDevice> WfsCoreEngine::ensure_attached() const {
  if (!wfs_device_) {
    throw std::runtime_error("wfs_core is not attached");
  }
  return wfs_device_;
}

void WfsCoreEngine::mkdir(const std::string& path) {
  auto device = ensure_attached();
  auto normalized = validate_and_normalize_path(path);
  resolve_directory(device, normalized, true);
}

void WfsCoreEngine::create_file(const std::string& path, uint32_t size_hint) {
  auto device = ensure_attached();
  auto normalized = validate_and_normalize_path(path, false);
  auto [parent, leaf] = parent_and_leaf(normalized);
  if (leaf.empty()) {
    throw std::runtime_error("invalid file path");
  }

  const auto target_size = static_cast<size_t>(size_hint > 0 ? size_hint : 0);
  auto directory = resolve_directory(device, parent, true);
  auto existing = directory->GetFile(leaf);
  if (existing.has_value()) {
    (*existing)->Resize(target_size);
    return;
  }

  if (existing.error() != WfsError::kEntryNotFound) {
    throw WfsException(existing.error());
  }

  auto created = directory->CreateFile(leaf, size_hint > 0 ? size_hint : 0, 0, 0, 0644, true);
  if (!created.has_value()) {
    throw WfsException(created.error());
  }
  (*created)->Resize(target_size);
}

size_t WfsCoreEngine::write_stream(const std::string& path, const std::vector<std::byte>& data, uint32_t offset) {
  if (offset != 0) {
    throw std::runtime_error("non-zero write offset is not supported by native writer");
  }
  auto device = ensure_attached();
  auto normalized = validate_and_normalize_path(path, false);
  auto file = device->GetFile(normalized);
  if (!file) {
    throw std::runtime_error("target file not found");
  }
  File::file_device file_device(file);
  if (data.empty()) {
    return 0;
  }
  auto wrote = file_device.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
  if (wrote < 0) {
    throw std::runtime_error("write failed");
  }
  return static_cast<size_t>(wrote);
}

void WfsCoreEngine::remove(const std::string& path) {
  auto device = ensure_attached();
  auto normalized = validate_and_normalize_path(path, false);
  auto [parent, leaf] = parent_and_leaf(normalized);
  if (leaf.empty()) {
    throw std::runtime_error("invalid path for delete");
  }
  auto directory = resolve_directory(device, parent, false);
  delete_entry_recursive(directory, leaf);
}

std::vector<std::string> WfsCoreEngine::list_titles() {
  auto device = ensure_attached();
  std::vector<std::string> titles;

  std::shared_ptr<Directory> titles_root;
  try {
    titles_root = resolve_directory(device, "/usr/title", false);
  } catch (const WfsException& exc) {
    if (exc.error() == WfsError::kEntryNotFound) {
      return titles;
    }
    throw;
  }

  for (auto it = titles_root->begin(); it != titles_root->end(); ++it) {
    auto entry = *it;
    if (!entry.entry.has_value()) {
      throw WfsException(entry.entry.error());
    }
    if (entry.entry.value()->is_directory()) {
      titles.push_back(entry.name);
    }
  }

  std::sort(titles.begin(), titles.end());
  return titles;
}

void WfsCoreEngine::remove_title(const std::string& title_id) {
  auto safe_title_id = validate_title_id(title_id);
  remove("/usr/title/" + safe_title_id);
}

void WfsCoreEngine::flush() {
  auto device = ensure_attached();
  device->Flush();
}

IntegrityReport WfsCoreEngine::integrity_check(const std::string& scope) {
  auto device = ensure_attached();
  auto normalized = validate_and_normalize_path(scope.empty() ? "/" : scope);
  uint64_t files = 0;
  uint64_t bytes = 0;

  if (normalized == "/") {
    auto root = resolve_directory(device, normalized, false);
    scan_directory(root, files, bytes);
    return {.ok = true, .files = files, .bytes = bytes, .scope = normalized, .reason = ""};
  }

  auto entry = device->GetEntry(normalized);
  if (!entry) {
    return {.ok = false, .files = 0, .bytes = 0, .scope = normalized, .reason = "entry_not_found"};
  }
  if (entry->is_file()) {
    auto file = std::dynamic_pointer_cast<File>(entry);
    if (!file) {
      return {.ok = false, .files = 0, .bytes = 0, .scope = normalized, .reason = "invalid_file_entry"};
    }
    return {.ok = true, .files = 1, .bytes = file->Size(), .scope = normalized, .reason = ""};
  }

  auto dir = std::dynamic_pointer_cast<Directory>(entry);
  if (!dir) {
    return {.ok = false, .files = 0, .bytes = 0, .scope = normalized, .reason = "invalid_directory_entry"};
  }
  scan_directory(dir, files, bytes);
  return {.ok = true, .files = files, .bytes = bytes, .scope = normalized, .reason = ""};
}

void WfsCoreEngine::detach() {
  if (wfs_device_) {
    wfs_device_->Flush();
  }
  wfs_device_.reset();
  device_path_.clear();
  fingerprint_.clear();
}
