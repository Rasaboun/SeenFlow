#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
sdk_root=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}
if [ -z "$sdk_root" ]; then
  echo "Set ANDROID_SDK_ROOT to the Android SDK directory." >&2
  exit 1
fi

platform="$sdk_root/platforms/android-34/android.jar"
build_tools="$sdk_root/build-tools/35.0.0"
fixture="$repo_root/examples/fixtures/android"
output="$repo_root/.maestro-vision/fixtures/android"
classes="$output/classes"
keystore="$output/debug.keystore"

rm -rf "$output"
mkdir -p "$classes" "$output/compiled" "$output/dex"
"$build_tools/aapt2" compile --dir "$fixture/res" -o "$output/compiled/resources.zip"
"$build_tools/aapt2" link \
  -I "$platform" \
  --manifest "$fixture/AndroidManifest.xml" \
  --java "$output/generated" \
  -o "$output/base.apk" \
  "$output/compiled/resources.zip"
javac --release 8 -Xlint:-options -classpath "$platform" -d "$classes" \
  "$fixture/src/com/example/maestrovisionfixture/MainActivity.java" \
  "$output/generated/com/example/maestrovisionfixture/R.java"
jar --create --file "$output/classes.jar" -C "$classes" .
"$build_tools/d8" --lib "$platform" --output "$output/dex" "$output/classes.jar"
(cd "$output/dex" && zip -q "$output/base.apk" classes.dex)
"$build_tools/zipalign" -f 4 "$output/base.apk" "$output/MaestroVisionFixture.apk"
keytool -genkeypair -noprompt -keystore "$keystore" -storepass android -keypass android \
  -alias androiddebugkey -dname "CN=Android Debug,O=Android,C=US" \
  -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
"$build_tools/apksigner" sign --ks "$keystore" --ks-pass pass:android \
  --key-pass pass:android "$output/MaestroVisionFixture.apk"
"$build_tools/apksigner" verify "$output/MaestroVisionFixture.apk"
printf '%s\n' "$output/MaestroVisionFixture.apk"
