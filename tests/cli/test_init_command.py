"""CLI init 命令测试。"""

import asyncio

from click.testing import CliRunner

from src.cli.main import cli


class TestInitCommand:
    """x-watcher init 命令测试。"""

    def test_init_no_input_missing_required(self):
        """非交互模式缺少必填参数时报错。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--no-input"])
        assert result.exit_code != 0
        assert "twitter-api-key" in result.output.lower() or result.exit_code == 1

    def test_init_no_input_with_all_params(self, tmp_path, monkeypatch):
        """非交互模式提供所有参数时成功。"""
        monkeypatch.chdir(tmp_path)
        # 设置必要的环境变量使 Settings 不会报错
        monkeypatch.setenv("TWITTER_API_KEY", "test-key")
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "--no-input",
                "--twitter-api-key=test-twitter-key",
                "--skip-db",
                "--skip-validate",
            ],
        )

        assert result.exit_code == 0
        assert "初始化完成" in result.output

        # 检查 .env 文件生成
        env_path = tmp_path / ".env"
        assert env_path.exists()
        env_content = env_path.read_text(encoding="utf-8")
        assert "TWITTER_API_KEY=test-twitter-key" in env_content
        assert "LLM" + "_" not in env_content
        assert "AUTO_" + "SUMMARIZATION" not in env_content

    def test_init_no_input_skip_existing_env(self, tmp_path, monkeypatch):
        """非交互模式下已有 .env 时跳过。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TWITTER_API_KEY", "test-key")
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")

        # 预先创建 .env
        (tmp_path / ".env").write_text("EXISTING=true\n")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "--no-input",
                "--twitter-api-key=key",
                "--skip-db",
                "--skip-validate",
            ],
        )

        assert result.exit_code == 0
        # 原始 .env 应该保留
        assert "EXISTING=true" in (tmp_path / ".env").read_text(encoding="utf-8")

    def test_init_creates_api_key_for_admin(self, tmp_path, monkeypatch):
        """init 创建管理员时应同时生成 API Key 并在输出中显示。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TWITTER_API_KEY", "test-key")
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

        from src.config import clear_settings_cache
        clear_settings_cache()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "--no-input",
                "--twitter-api-key=test-twitter-key",
                "--skip-validate",
            ],
        )

        assert result.exit_code == 0, f"init failed: {result.output}"
        assert "sna_" in result.output  # API Key 格式
        assert "仅显示一次" in result.output

        from src.user.infrastructure.file_user_repository import FileUserStore

        store = FileUserStore(tmp_path)
        user = asyncio.run(store.get_user_by_email("admin@x-watcher.local"))
        assert user is not None
        keys = asyncio.run(store.get_keys_by_user(user.id))
        assert len(keys) == 1
        assert keys[0].key_prefix.startswith("sna_")
        assert keys[0].name == "default"

        clear_settings_cache()

    def test_init_generates_jwt_secret(self, tmp_path, monkeypatch):
        """自动生成 JWT 密钥。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TWITTER_API_KEY", "test-key")
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "--no-input",
                "--twitter-api-key=key",
                "--skip-db",
                "--skip-validate",
            ],
        )

        assert result.exit_code == 0
        env_content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "JWT_SECRET_KEY=" in env_content
        # JWT 密钥不应该是默认值
        assert "change-me-in-production" not in env_content
        assert "LLM" + "_" not in env_content
        assert "AUTO_" + "SUMMARIZATION" not in env_content


class TestValidateCommand:
    """x-watcher validate 命令测试。"""

    def test_validate_runs(self, monkeypatch):
        """validate 命令能正常运行。"""
        monkeypatch.setenv("TWITTER_API_KEY", "")
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test")

        runner = CliRunner()
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code == 0
        assert "配置验证" in result.output


class TestServeCommand:
    """x-watcher serve 命令测试。"""

    def test_serve_help(self):
        """serve --help 正常输出。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
