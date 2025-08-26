# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2

<#
Taken from: https://github.com/saltstack/salt-windows-nsis/blob/main/scripts/install_vs_buildtools.bat

.SYNOPSIS
Script that installs Visual Studio Build Tools
.DESCRIPTION
This script installs the Visual Studio Build Tools if they are not already
present on the system. Visual Studio Build Tools are the binaries and libraries
needed to build Python from source.
.EXAMPLE
install_vc_buildtools.ps1
#>

# Script Preferences
$ProgressPreference = "SilentlyContinue"
$ErrorActionPreference = "Stop"

#-------------------------------------------------------------------------------
# Start the Script
#-------------------------------------------------------------------------------

Write-Host $("=" * 80)
Write-Host "Install Visual Studio Build Tools" -ForegroundColor Cyan
Write-Host $("-" * 80)

#-------------------------------------------------------------------------------
# Script Variables
#-------------------------------------------------------------------------------

# Dependency Variables
$VS_BLD_TOOLS   = "https://aka.ms/vs/15/release/vs_buildtools.exe"
$VS_CL_BIN      = "${env:ProgramFiles(x86)}\Microsoft Visual Studio 14.0\VC\bin\cl.exe"
$MSBUILD_BIN    = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2017\BuildTools\MSBuild\15.0\Bin\msbuild.exe"

#-------------------------------------------------------------------------------
# Visual Studio
#-------------------------------------------------------------------------------

$install_build_tools = $false
Write-Host "Confirming Presence of Visual Studio Build Tools: " -NoNewline
@($VS_CL_BIN, $MSBUILD_BIN) | ForEach-Object {
    if ( ! (Test-Path -Path $_) ) {
        $install_build_tools = $true
    }
}

if ( $install_build_tools ) {
    Write-Host "Missing" -ForegroundColor Yellow

    Write-Host "Checking available disk space: " -NoNewLine
    $available = (Get-PSDrive $env:SystemDrive.Trim(":")).Free
    if ( $available -gt (1024 * 1024 * 1024 * 9.1) ) {
        Write-Host "Success" -ForegroundColor Green
    } else {
        Write-Host "Failed" -ForegroundColor Red
        Write-Host "Not enough disk space"
        exit 1
    }

    Write-Host "Downloading Visual Studio 2017 build tools: " -NoNewline
    Invoke-WebRequest -Uri "$VS_BLD_TOOLS" -OutFile "$env:TEMP\vs_buildtools.exe"
    if ( Test-Path -Path "$env:TEMP\vs_buildtools.exe" ) {
        Write-Host "Success" -ForegroundColor Green
    } else {
        Write-Host "Failed" -ForegroundColor Red
        exit 1
    }

    Write-Host "Creating Layout for Visual Studio 2017 build tools: " -NoNewline
    if ( ! (Test-Path -Path "$($env:TEMP)\build_tools") ) {
        New-Item -Path "$($env:TEMP)\build_tools" -ItemType Directory | Out-Null
    }

    Start-Process -FilePath "$env:TEMP\vs_buildtools.exe" `
                  -ArgumentList "--layout `"$env:TEMP\build_tools`"", `
                                "--add Microsoft.VisualStudio.Workload.MSBuildTools", `
                                "--add Microsoft.VisualStudio.Workload.VCTools", `
                                "--add Microsoft.VisualStudio.Component.VC.140", `
                                "--lang en-US", `
                                "--includeRecommended", `
                                "--quiet", `
                                "--wait" `
                  -Wait -WindowStyle Hidden
    if ( Test-Path -Path "$env:TEMP\build_tools\vs_buildtools.exe" ) {
        Write-Host "Success" -ForegroundColor Green
    } else {
        Write-Host "Failed" -ForegroundColor Red
        exit 1
    }

    # Serial: 28cc3a25bfba44ac449a9b586b4339a
    # Hash: 3b1efd3a66ea28b16697394703a72ca340a05bd5
    if (! (Test-Path -Path Cert:\LocalMachine\Root\3b1efd3a66ea28b16697394703a72ca340a05bd5) ) {
        Write-Host "Installing Certificate Sign Root Certificate: " -NoNewLine
        Start-Process -FilePath "certutil" `
                      -ArgumentList "-addstore", `
                                    "Root", `
                                    "$($env:TEMP)\build_tools\certificates\manifestCounterSignRootCertificate.cer" `
                      -Wait -WindowStyle Hidden
        if ( Test-Path -Path Cert:\LocalMachine\Root\3b1efd3a66ea28b16697394703a72ca340a05bd5 ) {
            Write-Host "Success" -ForegroundColor Green
        } else {
            Write-Host "Failed" -ForegroundColor Yellow
        }
    }

    # Serial: 3f8bc8b5fc9fb29643b569d66c42e144
    # Hash: 8f43288ad272f3103b6fb1428485ea3014c0bcfe
    if (! (Test-Path -Path Cert:\LocalMachine\Root\8f43288ad272f3103b6fb1428485ea3014c0bcfe) ) {
        Write-Host "Installing Certificate Root Certificate: " -NoNewLine
        Start-Process -FilePath "certutil" `
                  -ArgumentList "-addstore", `
                                "Root", `
                                "$($env:TEMP)\build_tools\certificates\manifestRootCertificate.cer" `
                  -Wait -WindowStyle Hidden
        if ( Test-Path -Path Cert:\LocalMachine\Root\8f43288ad272f3103b6fb1428485ea3014c0bcfe ) {
            Write-Host "Success" -ForegroundColor Green
        } else {
            Write-Host "Failed" -ForegroundColor Yellow
        }
    }

    Write-Host "Installing Visual Studio 2017 build tools: " -NoNewline
    Start-Process -FilePath "$env:TEMP\build_tools\vs_setup.exe" `
                  -ArgumentList "--wait", "--noweb", "--quiet" `
                  -Wait
    @($VS_CL_BIN, $MSBUILD_BIN) | ForEach-Object {
        if ( ! (Test-Path -Path $_) ) {
            Write-Host "Failed" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Success" -ForegroundColor Green
} else {
    Write-Host "Success" -ForegroundColor Green
}

#-------------------------------------------------------------------------------
# Finished
#-------------------------------------------------------------------------------
Write-Host $("-" * 80)
Write-Host "Install Visual Studio Build Tools Completed" -ForegroundColor Cyan
Write-Host $("=" * 80)
