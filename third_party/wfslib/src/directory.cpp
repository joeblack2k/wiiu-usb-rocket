/*
 * Copyright (C) 2017 koolkdev
 *
 * This software may be modified and distributed under the terms
 * of the MIT license.  See the LICENSE file for details.
 */

#include "directory.h"

#include <algorithm>
#include <bit>
#include <cctype>
#include <cstring>
#include <ctime>
#include <ranges>
#include <utility>
#include <vector>

#include "file.h"
#include "quota_area.h"

namespace {

std::string normalize_key(std::string_view name) {
  std::string normalized{name};
  std::ranges::transform(normalized, normalized.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return normalized;
}

bool is_valid_child_name(std::string_view name) {
  if (name.empty()) {
    return false;
  }
  if (name == "." || name == "..") {
    return false;
  }
  return std::ranges::find(name, '/') == name.end();
}

uint8_t metadata_log2_from_total_size(size_t size) {
  if (size == 0) {
    return 6;
  }
  uint8_t log2 = static_cast<uint8_t>(std::bit_width(size - 1));
  if ((size_t{1} << log2) < size) {
    ++log2;
  }
  if (log2 < 6) {
    log2 = 6;
  }
  return log2;
}

std::vector<std::byte> make_entry_metadata(std::string_view name,
                                           uint32_t flags,
                                           uint32_t size_on_disk,
                                           uint32_t file_size,
                                           uint32_t directory_block_number,
                                           uint32_t owner,
                                           uint32_t group,
                                           uint32_t mode,
                                           uint8_t size_category,
                                           uint8_t metadata_log2_size) {
  auto lowercase_name = normalize_key(name);
  size_t bitmap_size = div_ceil(lowercase_name.size(), size_t{8});
  size_t total_size = std::max(size_t{1} << metadata_log2_size,
                               offsetof(EntryMetadata, case_bitmap) + bitmap_size + size_on_disk);
  auto final_log2 = metadata_log2_from_total_size(total_size);
  total_size = size_t{1} << final_log2;

  std::vector<std::byte> payload(total_size);
  auto* metadata = reinterpret_cast<EntryMetadata*>(payload.data());
  std::memset(metadata, 0, total_size);

  auto now = static_cast<uint32_t>(std::time(nullptr));
  metadata->flags = flags;
  metadata->size_on_disk = size_on_disk;
  metadata->ctime = now;
  metadata->mtime = now;
  metadata->unknown = 0;
  metadata->file_size = file_size;
  metadata->directory_block_number = directory_block_number;
  metadata->permissions.owner = owner;
  metadata->permissions.group = group;
  metadata->permissions.mode = mode;
  metadata->metadata_log2_size = final_log2;
  metadata->size_category = size_category;
  metadata->filename_length = static_cast<uint8_t>(lowercase_name.size());

  auto* bitmap = reinterpret_cast<uint8_t*>(&metadata->case_bitmap);
  std::memset(bitmap, 0, bitmap_size);
  for (size_t i = 0; i < name.size(); ++i) {
    auto raw = static_cast<unsigned char>(name[i]);
    if (std::isupper(raw)) {
      bitmap[i / 8] |= static_cast<uint8_t>(1u << (i % 8));
    }
  }

  return payload;
}

}  // namespace

Directory::Directory(std::string name,
                     MetadataRef metadata,
                     std::shared_ptr<QuotaArea> quota,
                     std::shared_ptr<Block> block)
    : Entry(std::move(name), std::move(metadata)),
      quota_(std::move(quota)),
      block_(std::move(block)),
      map_{quota_, block_} {}

std::expected<std::shared_ptr<Entry>, WfsError> Directory::GetEntry(std::string_view name) const {
  try {
    auto it = find(name);
    if (it.is_end()) {
      return std::unexpected(WfsError::kEntryNotFound);
    }
    return (*it).entry;
  } catch (const WfsException& e) {
    return std::unexpected(e.error());
  }
}

std::expected<std::shared_ptr<Directory>, WfsError> Directory::GetDirectory(std::string_view name) const {
  auto entry = GetEntry(name);
  if (!entry.has_value())
    return std::unexpected(entry.error());
  if (!(*entry)->is_directory()) {
    // Not a directory
    return std::unexpected(kNotDirectory);
  }
  return std::dynamic_pointer_cast<Directory>(*entry);
}

std::expected<std::shared_ptr<File>, WfsError> Directory::GetFile(std::string_view name) const {
  auto entry = GetEntry(name);
  if (!entry.has_value())
    return std::unexpected(entry.error());
  if (!(*entry)->is_file()) {
    // Not a file
    return std::unexpected(kNotFile);
  }
  return std::dynamic_pointer_cast<File>(*entry);
}

std::expected<std::shared_ptr<Directory>, WfsError> Directory::CreateDirectory(std::string_view name,
                                                                                uint32_t owner,
                                                                                uint32_t group,
                                                                                uint32_t mode) {
  if (!is_valid_child_name(name)) {
    return std::unexpected(kInvalidArgument);
  }
  auto key = normalize_key(name);
  auto existing = GetEntry(key);
  if (existing.has_value()) {
    return std::unexpected(kAlreadyExists);
  }

  auto block = quota_->AllocMetadataBlock();
  if (!block.has_value()) {
    return std::unexpected(block.error());
  }

  DirectoryMap new_map{quota_, *block};
  new_map.Init();

  uint32_t directory_block_number = quota_->to_area_block_number((*block)->physical_block_number());
  auto metadata = make_entry_metadata(name,
                                      EntryMetadata::Flags::DIRECTORY,
                                      /*size_on_disk=*/0,
                                      /*file_size=*/0,
                                      directory_block_number,
                                      owner,
                                      group,
                                      mode,
                                      /*size_category=*/0,
                                      /*metadata_log2_size=*/6);

  if (!map_.insert(key, reinterpret_cast<const EntryMetadata*>(metadata.data()))) {
    return std::unexpected(kNoSpace);
  }
  return GetDirectory(key);
}

std::expected<std::shared_ptr<File>, WfsError> Directory::CreateFile(std::string_view name,
                                                                     uint32_t size_on_disk,
                                                                     uint32_t owner,
                                                                     uint32_t group,
                                                                     uint32_t mode,
                                                                     bool encrypted) {
  if (!is_valid_child_name(name)) {
    return std::unexpected(kInvalidArgument);
  }
  auto key = normalize_key(name);
  auto existing = GetEntry(key);
  if (existing.has_value()) {
    return std::unexpected(kAlreadyExists);
  }

  auto metadata = make_entry_metadata(name,
                                      encrypted ? 0 : EntryMetadata::Flags::UNENCRYPTED_FILE,
                                      size_on_disk,
                                      /*file_size=*/0,
                                      /*directory_block_number=*/0,
                                      owner,
                                      group,
                                      mode,
                                      /*size_category=*/0,
                                      /*metadata_log2_size=*/9);
  if (metadata.size() > (size_t{1} << 10)) {
    return std::unexpected(kOperationNotSupported);
  }

  if (!map_.insert(key, reinterpret_cast<const EntryMetadata*>(metadata.data()))) {
    return std::unexpected(kNoSpace);
  }
  return GetFile(key);
}

std::expected<void, WfsError> Directory::DeleteEntry(std::string_view name) {
  if (!is_valid_child_name(name)) {
    return std::unexpected(kInvalidArgument);
  }
  auto key = normalize_key(name);
  auto existing = GetEntry(key);
  if (!existing.has_value()) {
    return std::unexpected(existing.error());
  }
  if ((*existing)->is_directory()) {
    auto child = std::dynamic_pointer_cast<Directory>(*existing);
    if (!child) {
      return std::unexpected(kNotDirectory);
    }
    if (child->size() != 0) {
      return std::unexpected(kDirectoryNotEmpty);
    }
  }
  if (!map_.erase(key)) {
    return std::unexpected(kEntryNotFound);
  }
  return {};
}

Directory::iterator Directory::find(std::string_view key) const {
  std::string lowercase_key{key};
  // to lowercase
  std::ranges::transform(lowercase_key, lowercase_key.begin(), [](char c) { return std::tolower(c); });
  return {map_.find(lowercase_key)};
}
