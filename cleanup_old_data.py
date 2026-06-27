import argparse

from service.maintenance_service import cleanup_old_data, get_storage_stats


def main():
    parser = argparse.ArgumentParser(description="清理几个月以前的行程记录，并可先自动归档。")
    parser.add_argument("--months", type=int, required=True, help="保留最近几个月的数据，例如 6 表示清理 6 个月以前的数据")
    parser.add_argument("--no-backup", action="store_true", help="不生成归档备份，直接删除")
    parser.add_argument("--keep-photos", action="store_true", help="只删除数据库记录，不删除对应照片")
    parser.add_argument("--yes", action="store_true", help="跳过确认")
    args = parser.parse_args()

    before = get_storage_stats()
    print("清理前：", before)
    if not args.yes:
        confirm = input(f"确认清理 {args.months} 个月以前的数据？输入 YES 继续：")
        if confirm.strip().upper() != "YES":
            print("已取消")
            return

    result = cleanup_old_data(
        retention_months=args.months,
        backup_before_delete=not args.no_backup,
        delete_photos=not args.keep_photos,
    )
    after = get_storage_stats()
    print("清理结果：", result)
    print("清理后：", after)


if __name__ == "__main__":
    main()
