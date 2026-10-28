# Wrap the verified full workstation ZIP in a per-user, windowless extractor.
param(
    [Parameter(Mandatory = $true)][string]$PackageZip,
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Out) { throw "Output already exists: $Out" }
$package = (Resolve-Path -LiteralPath $PackageZip).Path
$hash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash
$source = @'
using System;
using System.ComponentModel;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Diagnostics;

class WorkstationSetup {
    const string ExpectedHash = "__PACKAGE_HASH__";
    static int exitCode = 1;
    [STAThread]
    static int Main(string[] args) {
        bool validateOnly = Array.IndexOf(args, "--validate-only") >= 0;
        if (validateOnly) {
            try { ExtractAndRun(true, null); return 0; }
            catch (InvalidDataException) { return 2; }
            catch (IOException) { return 2; }
            catch (UnauthorizedAccessException) { return 3; }
            catch (SecurityException) { return 4; }
            catch (CryptographicException) { return 4; }
            catch (ArgumentException) { return 2; }
            catch (NotSupportedException) { return 2; }
        }
        Application.EnableVisualStyles();
        Form form = new Form();
        form.Text = "LetterSys";
        form.Width = 460; form.Height = 160;
        form.StartPosition = FormStartPosition.CenterScreen;
        form.FormBorderStyle = FormBorderStyle.FixedDialog;
        form.MaximizeBox = false; form.MinimizeBox = false;
        form.ControlBox = false;
        Label label = new Label();
        label.Dock = DockStyle.Top; label.Height = 65;
        label.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;
        label.RightToLeft = RightToLeft.Yes;
        label.Text = "\u062C\u0627\u0631\u064D \u062A\u062C\u0647\u064A\u0632 \u0627\u0644\u062C\u0647\u0627\u0632...\r\n\u0627\u0646\u062A\u0638\u0631 \u062D\u062A\u0649 \u062A\u0638\u0647\u0631 \u0646\u0627\u0641\u0630\u0629 \u0627\u0644\u0645\u0648\u0627\u0641\u0642\u0629.";
        ProgressBar progress = new ProgressBar();
        progress.Dock = DockStyle.Bottom; progress.Style = ProgressBarStyle.Marquee;
        form.Controls.Add(label); form.Controls.Add(progress);
        form.Shown += delegate {
            Task.Factory.StartNew(delegate {
                try {
                    exitCode = ExtractAndRun(false, delegate {
                        form.BeginInvoke(new Action(form.Hide));
                    });
                }
                catch (InvalidDataException exception) { Report(exception); }
                catch (IOException exception) { Report(exception); }
                catch (UnauthorizedAccessException exception) { Report(exception); }
                catch (SecurityException exception) { Report(exception); }
                catch (Win32Exception exception) { Report(exception); }
                catch (CryptographicException exception) { Report(exception); }
                catch (ArgumentException exception) { Report(exception); }
                catch (NotSupportedException exception) { Report(exception); }
                finally { form.BeginInvoke(new Action(form.Close)); }
            });
        };
        Application.Run(form);
        return exitCode;
    }
    static void Report(Exception exception) {
        exitCode = 2;
        MessageBox.Show(
            "\u062A\u0639\u0630\u0631 \u062A\u062C\u0647\u064A\u0632 \u0627\u0644\u062C\u0647\u0627\u0632.\r\n" +
            "\u062A\u0648\u0627\u0635\u0644 \u0645\u0639 \u0645\u0633\u0624\u0648\u0644 \u0627\u0644\u0646\u0638\u0627\u0645.\r\n\r\n" +
            exception.Message, "LetterSys", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
    static void Cleanup(string directory, bool validateOnly) {
        for (int attempt = 0; attempt < 3; attempt++) {
            Exception failure;
            try { Directory.Delete(directory, true); return; }
            catch (DirectoryNotFoundException) { return; }
            catch (IOException exception) { failure = exception; }
            catch (UnauthorizedAccessException exception) { failure = exception; }
            if (attempt < 2) {
                System.Threading.Thread.Sleep(500);
                continue;
            }
            Trace.TraceWarning("LetterSys temporary-file cleanup failed: {0}: {1}", directory, failure.Message);
            if (!validateOnly) MessageBox.Show(
                "\u062A\u0639\u0630\u0631 \u062D\u0630\u0641 \u0628\u0639\u0636 \u0627\u0644\u0645\u0644\u0641\u0627\u062A \u0627\u0644\u0645\u0624\u0642\u062A\u0629.\r\n" +
                "\u0646\u062A\u064A\u062C\u0629 \u0627\u0644\u062A\u062C\u0647\u064A\u0632 \u0644\u0645 \u062A\u062A\u063A\u064A\u0631.\r\n\r\n" +
                directory + "\r\n" + failure.Message,
                "LetterSys", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
    static int ExtractAndRun(bool validateOnly, Action payloadReady) {
        string directory = Path.Combine(Path.GetTempPath(), "LetterSysSetup-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try {
            string zip = Path.Combine(directory, "payload.zip");
            Assembly assembly = Assembly.GetExecutingAssembly();
            string[] resources = assembly.GetManifestResourceNames();
            if (resources.Length != 1) throw new InvalidDataException("Installer payload is missing.");
            using (Stream input = assembly.GetManifestResourceStream(resources[0]))
            using (FileStream output = File.Create(zip)) { input.CopyTo(output); }
            using (SHA256 sha = SHA256.Create())
            using (FileStream stream = File.OpenRead(zip)) {
                string hash = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "");
                if (hash != ExpectedHash) throw new InvalidDataException("Installer payload checksum failed.");
            }
            string extracted = Path.Combine(directory, "package");
            string prefix = extracted + Path.DirectorySeparatorChar;
            using (ZipArchive archive = ZipFile.OpenRead(zip)) {
                foreach (ZipArchiveEntry entry in archive.Entries) {
                    string destination = Path.GetFullPath(Path.Combine(extracted, entry.FullName));
                    if (!destination.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("Unsafe installer archive path.");
                }
            }
            ZipFile.ExtractToDirectory(zip, extracted);
            string setup = Path.Combine(extracted, "Setup.vbs");
            if (!File.Exists(setup)) throw new InvalidDataException("Setup.vbs is missing.");
            if (validateOnly) return 0;
            if (payloadReady != null) payloadReady();
            ProcessStartInfo launch = new ProcessStartInfo(
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "wscript.exe"),
                "\"" + setup + "\"");
            launch.UseShellExecute = false; launch.CreateNoWindow = true;
            launch.WorkingDirectory = extracted;
            using (Process installer = Process.Start(launch)) {
                installer.WaitForExit();
                return installer.ExitCode;
            }
        } finally {
            Cleanup(directory, validateOnly);
        }
    }
}
'@
$source = $source.Replace('__PACKAGE_HASH__', $hash)
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$parameters = New-Object System.CodeDom.Compiler.CompilerParameters
$parameters.GenerateExecutable = $true
$parameters.GenerateInMemory = $false
$parameters.OutputAssembly = [System.IO.Path]::GetFullPath($Out)
$parameters.CompilerOptions = '/target:winexe /optimize+ /define:TRACE'
foreach ($assembly in @('System.dll', 'System.Core.dll', 'System.Windows.Forms.dll',
    'System.Drawing.dll', 'System.IO.Compression.dll', 'System.IO.Compression.FileSystem.dll')) {
    $null = $parameters.ReferencedAssemblies.Add($assembly)
}
$null = $parameters.EmbeddedResources.Add($package)
$result = $provider.CompileAssemblyFromSource($parameters, $source)
if ($result.Errors.HasErrors) {
    throw (($result.Errors | ForEach-Object { $_.ToString() }) -join "`n")
}
$process = Start-Process -FilePath $parameters.OutputAssembly -ArgumentList '--validate-only' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Extractor validation failed: $($process.ExitCode)" }
Write-Output "Built and verified windowless extractor: $($parameters.OutputAssembly)"
