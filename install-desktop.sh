#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
applications_dir="$data_dir/applications"
icons_dir="$data_dir/icons"
icon_path="$icons_dir/io.github.d4n1ss1m0.Notes.png"
mkdir -p "$applications_dir" "$icons_dir"
cp "$project_dir/Notes.png" "$icon_path"
cat > "$applications_dir/io.github.d4n1ss1m0.Notes.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Notes
Name[ru]=Заметки
Comment=Local notes application
Comment[ru]=Локальное приложение заметок
Exec="$project_dir/run.sh"
Icon=$icon_path
Terminal=false
Categories=Office;
StartupNotify=true
EOF
echo "Launcher installed: $applications_dir/io.github.d4n1ss1m0.Notes.desktop"
