set CL=/wd4819 %CL%

"C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe" "msvcstuff\vs2019\Exult.sln" /p:Configuration=Release /p:Platform=x64 /p:VcpkgOverlayPorts=msvcstuff\vs2019\overlay_ports
