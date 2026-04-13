"""Generate a complete StereoKit C# project from an Aether SceneIR.

Produces a dictionary of {filename: content} that together form a
buildable .NET project targeting Quest 3 via StereoKit.

StereoKit mapping:
  three.js BoxGeometry     → Mesh.GenerateCube
  three.js SphereGeometry  → Mesh.GenerateSphere
  three.js CylinderGeometry → Mesh.GenerateCylinder
  three.js ConeGeometry    → Mesh.GenerateCylinder (tapered)
  three.js PlaneGeometry   → Mesh.GeneratePlane
  MeshStandardMaterial     → Material.Default with color
  DirectionalLight         → Renderer.SkyLight
  AmbientLight             → Built-in SK ambient
  GLTF loading             → Model.FromFile()
  Fog                      → (annotation: not natively supported)
  Web Audio soundscape     → Sound.Generate() procedural
  Portal                   → UI.WindowBegin with teleport

CONDENSER annotations are embedded in the output so future passes
(human or AI) know what was preserved and what was shed.
"""

import math
import textwrap
from datetime import datetime


def _hex_to_rgb(hex_color):
    """Convert '#RRGGBB' to (r, g, b) floats 0-1."""
    h = hex_color.lstrip('#')
    if len(h) != 6:
        return (0.5, 0.5, 0.5)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r / 255.0, g / 255.0, b / 255.0)


def _cs_color(hex_color):
    """Return a StereoKit Color constructor string."""
    r, g, b = _hex_to_rgb(hex_color)
    return f'new Color({r:.3f}f, {g:.3f}f, {b:.3f}f)'


def _cs_vec3(xyz):
    """Return a StereoKit Vec3 from [x, y, z]."""
    return f'new Vec3({xyz[0]:.3f}f, {xyz[1]:.3f}f, {xyz[2]:.3f}f)'


def _deg_to_rad(deg):
    return deg * math.pi / 180.0


def generate(scene_ir):
    """Generate a complete StereoKit project from a SceneIR.

    Returns a dict of {relative_path: file_content}.
    """
    files = {}
    safe_name = scene_ir.slug.replace('-', '_')
    project_name = f'Aether_{safe_name}'
    env = scene_ir.environment

    # --- Program.cs ---
    entity_inits = []
    entity_updates = []

    for ent in scene_ir.entities:
        var = f'ent_{ent.id}'
        pos = _cs_vec3(ent.position)
        rot_x = _deg_to_rad(ent.rotation[0])
        rot_y = _deg_to_rad(ent.rotation[1])
        rot_z = _deg_to_rad(ent.rotation[2])
        scale = _cs_vec3(ent.scale)

        if ent.asset_url:
            # GLTF model
            entity_inits.append(
                f'        // Entity: {ent.name or "model"}\n'
                f'        Model {var}_model = Model.FromFile("{ent.asset_url.split("/")[-1]}");\n'
                f'        Pose {var}_pose = new Pose({pos}, '
                f'Quat.FromAngles({ent.rotation[0]:.1f}f, {ent.rotation[1]:.1f}f, {ent.rotation[2]:.1f}f));\n'
                f'        Vec3 {var}_scale = {scale};'
            )
            entity_updates.append(
                f'            // {ent.name or "model"}\n'
                f'            {var}_model.Draw(Matrix.TRS({var}_pose.position, {var}_pose.orientation, {var}_scale));'
            )
        elif ent.primitive:
            # Primitive geometry
            mesh_gen = {
                'box': 'Mesh.GenerateCube(Vec3.One)',
                'sphere': 'Mesh.GenerateSphere(0.5f)',
                'cylinder': 'Mesh.GenerateCylinder(0.5f, 1.0f, Vec3.Up)',
                'cone': 'Mesh.GenerateCylinder(0.5f, 1.0f, Vec3.Up, 0f)',
                'plane': 'Mesh.GeneratePlane(Vec2.One)',
                'torus': 'Mesh.GenerateSphere(0.5f)',  # no torus in SK; approximate
                'ring': 'Mesh.GeneratePlane(Vec2.One)',  # approximate
            }.get(ent.primitive, 'Mesh.GenerateCube(Vec3.One)')

            color = _cs_color(ent.primitive_color)

            entity_inits.append(
                f'        // Entity: {ent.name or ent.primitive}\n'
                f'        Mesh {var}_mesh = {mesh_gen};\n'
                f'        Material {var}_mat = Material.Default.Copy();\n'
                f'        {var}_mat.SetColor("color", {color});\n'
                f'        Pose {var}_pose = new Pose({pos}, '
                f'Quat.FromAngles({ent.rotation[0]:.1f}f, {ent.rotation[1]:.1f}f, {ent.rotation[2]:.1f}f));\n'
                f'        Vec3 {var}_scale = {scale};'
            )

            # Behaviors
            draw_line = (
                f'            {var}_mesh.Draw({var}_mat, '
                f'Matrix.TRS({var}_pose.position, {var}_pose.orientation, {var}_scale));'
            )

            if ent.behavior == 'rotate':
                entity_updates.append(
                    f'            // {ent.name or ent.primitive} (rotate)\n'
                    f'            {var}_pose.orientation *= '
                    f'Quat.FromAngles(0, {ent.behavior_speed * 60:.1f}f * Time.Stepf, 0);\n'
                    f'{draw_line}'
                )
            elif ent.behavior == 'bob':
                entity_updates.append(
                    f'            // {ent.name or ent.primitive} (bob)\n'
                    f'            {var}_pose.position.y += '
                    f'MathF.Sin(Time.Totalf * {ent.behavior_speed:.1f}f * 2f) * 0.003f;\n'
                    f'{draw_line}'
                )
            else:
                entity_updates.append(
                    f'            // {ent.name or ent.primitive}\n'
                    f'{draw_line}'
                )

        # Script annotations (JS → C# translation notes)
        for script in ent.scripts:
            entity_updates.append(
                f'            // CONDENSER: Script ({script.event}) on {ent.name or ent.primitive}\n'
                f'            // Original JS not auto-translated. Event: {script.event}\n'
                f'            // Props: {script.props}\n'
                f'            // Manual C# translation needed for:\n'
                f'            // {script.code[:120].replace(chr(10), " ")}...'
            )

    # Portals
    for portal in scene_ir.portals:
        pos = _cs_vec3(portal.position)
        entity_updates.append(
            f'            // Portal: {portal.label}\n'
            f'            Pose portalPose = new Pose({pos} + Vec3.Up * {portal.height / 2:.1f}f, Quat.Identity);\n'
            f'            UI.WindowBegin("{portal.label}", ref portalPose, '
            f'new Vec2({portal.width:.1f}f, {portal.height:.1f}f));\n'
            f'            if (UI.Button("Enter {portal.target_title}"))\n'
            f'                Log.Info("Portal to: {portal.target_slug}");\n'
            f'            UI.WindowEnd();'
        )

    program_cs = textwrap.dedent(f"""\
        // CONDENSER: StereoKit distillation of Aether world "{scene_ir.title}"
        // Generated: {datetime.now():%Y-%m-%d %H:%M}
        // Source: Velour Aether → Condenser → StereoKit
        //
        // What survived: geometry, transforms, colors, behaviors (rotate/bob),
        //   lighting setup, ground plane, portals as UI windows.
        // What was shed: Web Audio soundscapes (need Sound.Generate()),
        //   fog (no StereoKit equivalent), HDRI reflections (use SK.SetSky),
        //   entity scripts (JS→C# requires manual translation),
        //   shadow maps (SK uses its own shadow system).
        //
        // CONDENSER: To add back shed features, see annotations below.

        using StereoKit;
        using System;

        namespace {project_name}
        {{
            class Program
            {{
                static void Main(string[] args)
                {{
                    SKSettings settings = new SKSettings
                    {{
                        appName = "{scene_ir.title}",
                        assetsFolder = "Assets",
                        displayPreference = DisplayMode.MixedReality,
                    }};

                    if (!SK.Initialize(settings))
                        return;

                    // --- Environment ---
                    // CONDENSER: Sky color {env.sky_color}, ground {env.ground_color}
                    Renderer.SkyLight = new SphericalHarmonics(
                        {_cs_color(env.sky_color)},
                        {_cs_color(env.ground_color)}
                    );

                    // Ground plane
                    Mesh groundMesh = Mesh.GeneratePlane(
                        new Vec2({env.ground_size:.0f}f, {env.ground_size:.0f}f));
                    Material groundMat = Material.Default.Copy();
                    groundMat.SetColor("color", {_cs_color(env.ground_color)});
                    Matrix groundTransform = Matrix.T(0, 0, 0);

                    // Spawn point
                    Pose headPose = new Pose({_cs_vec3(scene_ir.spawn)}, Quat.Identity);

        {chr(10).join(entity_inits)}

                    // --- Main loop ---
                    SK.Run(() =>
                    {{
                        // Ground
                        groundMesh.Draw(groundMat, groundTransform);

        {chr(10).join(entity_updates)}
                    }});
                }}
            }}
        }}
    """)

    files['Program.cs'] = program_cs

    # --- .csproj ---
    csproj = textwrap.dedent(f"""\
        <Project Sdk="Microsoft.NET.Sdk">
          <PropertyGroup>
            <OutputType>Exe</OutputType>
            <TargetFramework>net8.0</TargetFramework>
            <RuntimeIdentifier>android-arm64</RuntimeIdentifier>
            <AssemblyName>{project_name}</AssemblyName>
          </PropertyGroup>
          <ItemGroup>
            <PackageReference Include="StereoKit" Version="0.3.9" />
          </ItemGroup>
        </Project>
    """)
    files[f'{project_name}.csproj'] = csproj

    # --- build.sh ---
    build_sh = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # CONDENSER: Build script for {scene_ir.title} → Quest 3
        # Prerequisites: .NET 8 SDK, Android SDK (API 29+), NDK
        set -e

        echo "=== Building {project_name} for Quest 3 ==="

        # Restore NuGet packages
        dotnet restore

        # Build for Android ARM64 (Quest 3)
        dotnet publish -c Release -r android-arm64 --self-contained

        APK_DIR="bin/Release/net8.0-android/publish"
        echo ""
        echo "Build complete."
        echo "APK directory: $APK_DIR"
        echo ""
        echo "To sideload to Quest 3, run:"
        echo "  ./sideload.sh"
    """)
    files['build.sh'] = build_sh

    # --- sideload.sh ---
    sideload_sh = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # CONDENSER: Sideload {scene_ir.title} to Quest 3 via ADB/SideQuest
        set -e

        APK=$(find bin/Release -name "*.apk" 2>/dev/null | head -1)

        if [ -z "$APK" ]; then
            echo "No APK found. Run ./build.sh first."
            exit 1
        fi

        echo "=== Sideloading $APK to Quest 3 ==="

        # Check for ADB
        if command -v adb &>/dev/null; then
            echo "Using ADB..."
            adb install -r "$APK"
            echo "Installed via ADB."
        elif command -v sidequest &>/dev/null; then
            echo "Using SideQuest CLI..."
            sidequest install-apk "$APK"
            echo "Installed via SideQuest."
        else
            echo "Neither adb nor sidequest found in PATH."
            echo "Install Android SDK (adb) or SideQuest CLI."
            echo ""
            echo "Manual install: copy $APK to Quest 3 via SideQuest GUI."
            exit 1
        fi

        echo ""
        echo "Done. Look for '{scene_ir.title}' in Unknown Sources on Quest 3."
    """)
    files['sideload.sh'] = sideload_sh

    # --- Assets directory marker ---
    files['Assets/.gitkeep'] = '# Place GLTF/GLB models and textures here\n'

    # Copy asset manifest for reference
    asset_lines = []
    for ent in scene_ir.entities:
        if ent.asset_url:
            fname = ent.asset_url.split('/')[-1]
            asset_lines.append(f'  {fname}  ← {ent.name or "unnamed entity"}')
    if asset_lines:
        files['Assets/MANIFEST.txt'] = (
            f'# Assets needed for "{scene_ir.title}"\n'
            f'# Copy these GLTF/GLB files into this directory.\n'
            f'# Source: Velour media server\n\n'
            + '\n'.join(asset_lines) + '\n'
        )

    # --- README ---
    files['README.md'] = textwrap.dedent(f"""\
        # {scene_ir.title} — StereoKit (Quest 3)

        Generated by Velour Condenser from Aether world `{scene_ir.slug}`.

        ## Build

        ```bash
        chmod +x build.sh sideload.sh
        ./build.sh
        ```

        ## Sideload to Quest 3

        1. Enable Developer Mode on Quest 3
        2. Connect via USB or wireless ADB
        3. Run `./sideload.sh`
        4. Find the app in Unknown Sources

        ## Requirements

        - .NET 8 SDK
        - Android SDK (API 29+) with NDK
        - ADB or SideQuest CLI

        ## What was preserved

        - Geometry (primitives: {', '.join(set(e.primitive for e in scene_ir.entities if e.primitive))})
        - Transforms (position, rotation, scale)
        - Colors and materials
        - Behaviors: rotate, bob (others need manual translation)
        - Ground plane ({env.ground_size}m)
        - Portals as StereoKit UI windows

        ## What needs manual work

        - Entity scripts (JS → C# translation, see CONDENSER comments in Program.cs)
        - HDRI skybox (use `Renderer.SkyTex = Tex.FromFile(...)`)
        - Procedural soundscapes (use `Sound.Generate()`)
        - Fog (no direct StereoKit equivalent)
    """)

    return files
